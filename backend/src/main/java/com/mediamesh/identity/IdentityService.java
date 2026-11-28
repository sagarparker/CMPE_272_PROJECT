package com.mediamesh.identity;

import java.time.Instant;
import java.sql.Timestamp;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Service
public class IdentityService {
    public enum Role { ADMIN, UPLOADER, RESEARCHER }
    public record User(UUID id, String email, String displayName, List<String> roles, boolean primaryAdmin,
            List<String> requestedRoles, String requestStatus) {}
    public record AccessRequest(UUID id, User user, List<String> roles, String status) {}
    private final String adminEmail;
    private final JdbcTemplate jdbc;
    private final KeycloakAccounts keycloak;

    public IdentityService(JdbcTemplate jdbc, KeycloakAccounts keycloak,
            @Value("${mediamesh.security.admin-email:}") String adminEmail) {
        this.adminEmail = adminEmail.trim();
        this.jdbc = jdbc;
        this.keycloak = keycloak;
    }

    @Transactional
    public User authenticate(Jwt jwt) {
        if (!"google".equals(jwt.getClaimAsString("identity_provider"))
                || !Boolean.TRUE.equals(jwt.getClaimAsBoolean("email_verified")))
            throw new OAuth2AuthenticationException("invalid_token");
        String issuer = jwt.getIssuer().toString();
        String subject = jwt.getSubject();
        if (subject == null || subject.isBlank()) throw new OAuth2AuthenticationException("invalid_token");
        boolean admin = !adminEmail.isEmpty() && adminEmail.equalsIgnoreCase(jwt.getClaimAsString("email"));
        if (admin) jdbc.execute("SELECT pg_advisory_xact_lock(27201)");
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
        if (admin) {
            // A configured administrator change must not leave the old account privileged.
            jdbc.update("DELETE FROM user_roles WHERE role='ADMIN' AND user_id<>?", id);
            jdbc.update("UPDATE users SET primary_admin=false WHERE primary_admin AND id<>?", id);
            jdbc.update("""
                UPDATE users SET primary_admin=true WHERE id=?
                AND NOT EXISTS (SELECT 1 FROM users WHERE primary_admin AND id<>?)
                """, id, id);
            if (Boolean.TRUE.equals(jdbc.queryForObject("SELECT primary_admin FROM users WHERE id=?", Boolean.class, id))) {
                int granted = jdbc.update("INSERT INTO user_roles VALUES (?, 'ADMIN') ON CONFLICT DO NOTHING", id);
                if (granted == 1) audit(id, "BOOTSTRAP_ADMIN", id.toString(), "Verified Google administrator");
            }
        } else {
            jdbc.update("DELETE FROM user_roles WHERE user_id=? AND role='ADMIN'", id);
            jdbc.update("UPDATE users SET primary_admin=false WHERE id=?", id);
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
        return jdbc.query("SELECT id,email,display_name,primary_admin FROM users WHERE id=? AND deleted_at IS NULL", (rs, n) ->
                new User(rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3), roles(id),
                        rs.getBoolean(4), requestedRoles(id), requestStatus(id)), id)
                .stream().findFirst().orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,"User not found"));
    }
    public List<String> roles(UUID id) {
        return jdbc.queryForList("SELECT role FROM user_roles WHERE user_id=? ORDER BY role", String.class, id);
    }
    public List<User> users() {
        return jdbc.queryForList("SELECT id FROM users WHERE deleted_at IS NULL ORDER BY created_at", UUID.class).stream().map(this::user).toList();
    }
    private List<String> requestedRoles(UUID id) {
        return jdbc.queryForList("SELECT role FROM access_request_roles WHERE request_id=(SELECT id FROM access_requests WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 1) ORDER BY role", String.class, id);
    }
    private String requestStatus(UUID id) {
        return jdbc.queryForList("SELECT status FROM access_requests WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 1", String.class, id)
                .stream().findFirst().orElse("NONE");
    }
    @Transactional
    public User requestAccess(UUID id, Set<Role> roles) {
        jdbc.queryForObject("SELECT id FROM users WHERE id=? FOR UPDATE", UUID.class, id);
        if (roles.isEmpty() || roles.contains(Role.ADMIN))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Choose uploader, researcher, or both");
        if ("PENDING".equals(requestStatus(id)))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Your access request is already pending");
        if (user(id).roles().containsAll(roles.stream().map(Enum::name).toList()))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "You already have the selected roles");
        UUID request = UUID.randomUUID();
        jdbc.update("INSERT INTO access_requests(id,user_id) VALUES (?,?)", request, id);
        for (Role role : roles) jdbc.update("INSERT INTO access_request_roles VALUES (?,?)", request, role.name());
        audit(id, "REQUEST_ACCESS", request.toString(), roles.toString());
        return user(id);
    }
    public List<AccessRequest> requests() {
        return jdbc.query("SELECT id,user_id,status FROM access_requests WHERE status='PENDING' ORDER BY created_at", (rs,n) -> {
            UUID id = rs.getObject(1, UUID.class);
            return new AccessRequest(id, user(rs.getObject(2, UUID.class)),
                    jdbc.queryForList("SELECT role FROM access_request_roles WHERE request_id=? ORDER BY role", String.class, id), rs.getString(3));
        });
    }
    @Transactional
    public void decide(UUID actor, UUID request, boolean approve) {
        // Use the same lock order as account deletion and role editing.
        jdbc.execute("SELECT pg_advisory_xact_lock(27201)");
        var targets = jdbc.queryForList("SELECT user_id FROM access_requests WHERE id=? FOR UPDATE", UUID.class, request);
        if (targets.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Access request not found");
        UUID target = targets.get(0);
        user(target);
        if (jdbc.update("UPDATE access_requests SET status=?, reviewed_by=?, reviewed_at=clock_timestamp() WHERE id=? AND status='PENDING'",
                approve ? "APPROVED" : "REJECTED", actor, request) != 1)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "This request has already been reviewed");
        if (approve) jdbc.update("INSERT INTO user_roles SELECT ?,role FROM access_request_roles WHERE request_id=? ON CONFLICT DO NOTHING", target, request);
        audit(actor, approve ? "APPROVE_ACCESS" : "REJECT_ACCESS", request.toString(), target.toString());
    }
    @Transactional
    public User replaceRoles(UUID actor, UUID target, Set<Role> roles) {
        jdbc.execute("SELECT pg_advisory_xact_lock(27201)");
        User current = user(target);
        if (roles.contains(Role.ADMIN) != current.primaryAdmin())
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Administrator access is reserved for " + adminEmail);
        jdbc.update("DELETE FROM user_roles WHERE user_id=?", target);
        for (Role role : roles) jdbc.update("INSERT INTO user_roles VALUES (?,?)", target, role.name());
        audit(actor, "REPLACE_ROLES", target.toString(), roles.toString());
        return user(target);
    }
    /**
     * Removes the Keycloak login, roles and sessions; keeps the row for audit history and so the
     * person's uploads stay in the library. The sole administrator cannot be deleted.
     */
    @Transactional
    public void deleteUser(UUID actor, UUID target) {
        jdbc.execute("SELECT pg_advisory_xact_lock(27201)");
        if (actor.equals(target)) throw new ResponseStatusException(HttpStatus.CONFLICT, "You cannot delete your own account");
        User current = user(target);
        if (current.primaryAdmin())
            throw new ResponseStatusException(HttpStatus.CONFLICT, "The primary administrator cannot be deleted");
        keycloak.remove(jdbc.queryForObject("SELECT subject FROM users WHERE id=?", String.class, target));
        jdbc.update("UPDATE access_requests SET status='REJECTED',reviewed_by=?,reviewed_at=clock_timestamp() WHERE user_id=? AND status='PENDING'", actor, target);
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
