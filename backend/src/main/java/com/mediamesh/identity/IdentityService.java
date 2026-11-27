package com.mediamesh.identity;

import java.security.SecureRandom;
import java.time.Instant;
import java.sql.Timestamp;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Service
public class IdentityService {
    public enum Role { ADMIN, UPLOADER, RESEARCHER }
    public record User(UUID id, String email, String displayName, List<String> roles, boolean primaryAdmin) {}
    public record NewAccount(String username, String email, String firstName, String lastName, Role role) {}
    public record CreatedAccount(User user, String username, String temporaryPassword) {}
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final String PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
    private final JdbcTemplate jdbc;
    private final KeycloakAccounts keycloak;
    private final String issuer;
    private final String bootstrapSubject;

    public IdentityService(JdbcTemplate jdbc, KeycloakAccounts keycloak,
            @Value("${mediamesh.security.issuer}") String issuer,
            @Value("${mediamesh.security.bootstrap-subject:}") String bootstrapSubject) {
        this.jdbc = jdbc;
        this.keycloak = keycloak;
        this.issuer = issuer;
        this.bootstrapSubject = bootstrapSubject;
    }

    @Transactional
    public User authenticate(Jwt jwt) {
        String issuer = jwt.getIssuer().toString();
        String subject = jwt.getSubject();
        if (subject == null || subject.isBlank()) throw new OAuth2AuthenticationException("invalid_token");
        UUID candidate = UUID.randomUUID();
        jdbc.update("""
            INSERT INTO users(id, issuer, subject, email, display_name) VALUES (?,?,?,?,?)
            ON CONFLICT (issuer,subject) DO UPDATE
            SET email=EXCLUDED.email, display_name=EXCLUDED.display_name
            """, candidate, issuer, subject,
            Objects.toString(jwt.getClaimAsString("email"), ""),
            Objects.toString(jwt.getClaimAsString("name"), subject));
        UUID id = jdbc.queryForObject("SELECT id FROM users WHERE issuer=? AND subject=?", UUID.class, issuer, subject);
        if (jdbc.queryForObject("SELECT deleted_at IS NOT NULL FROM users WHERE id=?", Boolean.class, id))
            throw new OAuth2AuthenticationException("invalid_token");
        // Bootstrap once at account creation; a later revocation must stay revoked.
        if (candidate.equals(id) && subject.equals(bootstrapSubject)) {
            jdbc.update("INSERT INTO user_roles VALUES (?, 'ADMIN') ON CONFLICT DO NOTHING", id);
            audit(id, "BOOTSTRAP_ADMIN", id.toString(), "Explicit configured subject");
        }
        String sid = jwt.getClaimAsString("sid");
        if (sid == null || sid.isBlank()) throw new OAuth2AuthenticationException("invalid_token");
        Instant started = jwt.getClaimAsInstant("auth_time");
        if (started == null) started = jwt.getIssuedAt();
        if (started == null || started.isAfter(Instant.now().plusSeconds(60)))
            throw new OAuth2AuthenticationException("invalid_token");
        jdbc.update("INSERT INTO api_sessions(session_id,user_id,started_at) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                sid, id, Timestamp.from(started));
        int active = jdbc.update("""
            UPDATE api_sessions SET last_seen=clock_timestamp()
            WHERE session_id=? AND user_id=? AND NOT revoked
              AND last_seen > clock_timestamp()-interval '30 minutes'
              AND started_at > clock_timestamp()-interval '8 hours'
            """, sid, id);
        if (active != 1) throw new OAuth2AuthenticationException("invalid_token");
        return user(id);
    }

    public User user(UUID id) {
        return jdbc.query("SELECT id,email,display_name,issuer,subject FROM users WHERE id=? AND deleted_at IS NULL", (rs, n) ->
                new User(rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3), roles(id),
                        isPrimary(rs.getString(4), rs.getString(5))), id)
                .stream().findFirst().orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,"User not found"));
    }
    public List<String> roles(UUID id) {
        return jdbc.queryForList("SELECT role FROM user_roles WHERE user_id=? ORDER BY role", String.class, id);
    }
    public List<User> users() {
        return jdbc.queryForList("SELECT id FROM users WHERE deleted_at IS NULL ORDER BY created_at", UUID.class).stream().map(this::user).toList();
    }
    /** The configured bootstrap administrator is the only account that may grant or revoke ADMIN. */
    private boolean isPrimary(String userIssuer, String subject) {
        return !bootstrapSubject.isBlank() && bootstrapSubject.equals(subject) && issuer.equals(userIssuer);
    }
    private void requirePrimary(UUID actor, String message) {
        if (!user(actor).primaryAdmin()) throw new ResponseStatusException(HttpStatus.FORBIDDEN, message);
    }
    @Transactional
    public CreatedAccount createAccount(UUID actor, NewAccount account) {
        if (account.role() == Role.ADMIN) requirePrimary(actor, "Only the primary administrator can create administrators");
        String password = temporaryPassword();
        String subject = keycloak.create(account.username(), account.email(), account.firstName(), account.lastName(), password);
        try {
            UUID id = UUID.randomUUID();
            jdbc.update("INSERT INTO users(id, issuer, subject, email, display_name) VALUES (?,?,?,?,?)",
                    id, issuer, subject, account.email(), account.firstName() + " " + account.lastName());
            jdbc.update("INSERT INTO user_roles VALUES (?,?)", id, account.role().name());
            audit(actor, "CREATE_ACCOUNT", id.toString(), account.username() + " " + account.role());
            return new CreatedAccount(user(id), account.username(), password);
        } catch (RuntimeException e) {
            keycloak.delete(subject);
            throw e;
        }
    }
    private static String temporaryPassword() {
        var password = new StringBuilder();
        for (int i = 0; i < 20; i++) password.append(PASSWORD_ALPHABET.charAt(RANDOM.nextInt(PASSWORD_ALPHABET.length())));
        return password.toString();
    }
    @Transactional
    public User replaceRoles(UUID actor, UUID target, Set<Role> roles) {
        jdbc.execute("SELECT pg_advisory_xact_lock(27201)");
        User current = user(target);
        if (roles.contains(Role.ADMIN) != current.roles().contains("ADMIN"))
            requirePrimary(actor, "Only the primary administrator can grant or remove administrator access");
        if (current.primaryAdmin() && !roles.contains(Role.ADMIN))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "The primary administrator keeps administrator access");
        if (!roles.contains(Role.ADMIN) && roles(target).contains("ADMIN")
                && jdbc.queryForObject("SELECT count(*) FROM user_roles WHERE role='ADMIN'", Integer.class) == 1)
            throw new ResponseStatusException(HttpStatus.CONFLICT,"Keep at least one administrator");
        jdbc.update("DELETE FROM user_roles WHERE user_id=?", target);
        for (Role role : roles) jdbc.update("INSERT INTO user_roles VALUES (?,?)", target, role.name());
        audit(actor, "REPLACE_ROLES", target.toString(), roles.toString());
        return user(target);
    }
    /**
     * Removes the Keycloak login, roles and sessions; keeps the row for audit history and so the
     * person's uploads stay in the library. Deleting an administrator needs the primary admin.
     */
    @Transactional
    public void deleteUser(UUID actor, UUID target) {
        jdbc.execute("SELECT pg_advisory_xact_lock(27201)");
        if (actor.equals(target)) throw new ResponseStatusException(HttpStatus.CONFLICT, "You cannot delete your own account");
        User current = user(target);
        if (current.primaryAdmin())
            throw new ResponseStatusException(HttpStatus.CONFLICT, "The primary administrator cannot be deleted");
        if (current.roles().contains("ADMIN"))
            requirePrimary(actor, "Only the primary administrator can delete administrators");
        keycloak.remove(jdbc.queryForObject("SELECT subject FROM users WHERE id=?", String.class, target));
        jdbc.update("DELETE FROM user_roles WHERE user_id=?", target);
        jdbc.update("UPDATE api_sessions SET revoked=true WHERE user_id=?", target);
        jdbc.update("UPDATE users SET deleted_at=clock_timestamp() WHERE id=?", target);
        audit(actor, "DELETE_USER", target.toString(), current.email());
    }
    public void audit(UUID actor, String action, String target, String detail) {
        jdbc.update("INSERT INTO audit_events(actor_id,action,target,detail) VALUES (?,?,?,?)", actor,action,target,detail);
    }
    public void logout(String sid, UUID id) {
        jdbc.update("UPDATE api_sessions SET revoked=true WHERE session_id=? AND user_id=?", sid,id);
    }
}
