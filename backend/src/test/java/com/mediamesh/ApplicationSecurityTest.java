package com.mediamesh;

import com.nimbusds.jose.jwk.*;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jwt.*;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.*;
import com.mediamesh.storage.MediaStorage;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.mockito.Mockito.*;

@SpringBootTest(properties={"spring.flyway.target=200","spring.main.banner-mode=off"})
@AutoConfigureMockMvc
@Testcontainers
class ApplicationSecurityTest {
    static final RSAKey key;
    static final HttpServer jwks;
    static {
        try {
            key=new RSAKeyGenerator(2048).keyID("test").generate();
            jwks=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
            jwks.createContext("/jwks",exchange->{
                byte[] body=new JWKSet(key.toPublicJWK()).toString().getBytes();
                exchange.getResponseHeaders().set("Content-Type","application/json");
                exchange.sendResponseHeaders(200,body.length);
                try(var output=exchange.getResponseBody()){output.write(body);}
            });
            jwks.start();
        } catch(Exception e){throw new RuntimeException(e);}
    }
    @Container static final PostgreSQLContainer<?> postgres=new PostgreSQLContainer<>("postgres:16-alpine");
    @DynamicPropertySource static void properties(DynamicPropertyRegistry p){
        p.add("spring.datasource.url",postgres::getJdbcUrl);
        p.add("spring.datasource.username",postgres::getUsername);
        p.add("spring.datasource.password",postgres::getPassword);
        p.add("mediamesh.security.issuer",()->"https://identity.test/realms/mediamesh");
        p.add("mediamesh.security.jwk-set-uri",()->"http://127.0.0.1:"+jwks.getAddress().getPort()+"/jwks");
    }
    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @Autowired com.fasterxml.jackson.databind.ObjectMapper json;
    @MockBean MediaStorage storage;
    @MockBean com.mediamesh.media.MlSearchClient ml;
    @MockBean com.mediamesh.identity.KeycloakAccounts keycloak;
    @BeforeEach void reset(){
        // Later catalog migrations are beyond this security fixture target.
        jdbc.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS playback_key TEXT");
        jdbc.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS generated_description TEXT");
        jdbc.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ");
        if (!Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='primary_admin')", Boolean.class))) {
            new org.springframework.jdbc.datasource.init.ResourceDatabasePopulator(
                new org.springframework.core.io.ClassPathResource("db/migration/V407__google_access_approval.sql"))
                .execute(Objects.requireNonNull(jdbc.getDataSource()));
        }
        jdbc.execute("TRUNCATE access_request_roles,access_requests,api_sessions,audit_events,user_roles,users,assets CASCADE");}
    @AfterAll static void close(){jwks.stop(0);}
    String token(String subject) throws Exception {return token(subject,"mediamesh-api",new Date(System.currentTimeMillis()+900000));}
    String token(String subject,String audience,Date expiry) throws Exception {
        var claims=new JWTClaimsSet.Builder().issuer("https://identity.test/realms/mediamesh").subject(subject)
            .audience(audience).issueTime(new Date()).expirationTime(expiry).claim("sid","session-"+subject)
            .claim("auth_time",System.currentTimeMillis()/1000).claim("name",subject).claim("identity_provider","google").claim("email_verified",true).claim("email",subject.equals("admin") ? "sagar.parker@sjsu.edu" : subject+"@example.org").build();
        var jwt=new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("test").build(),claims);
        jwt.sign(new RSASSASigner(key));return jwt.serialize();
    }
    String userId(String token) throws Exception {
        var result=mvc.perform(get("/api/me").header("Authorization","Bearer "+token)).andExpect(status().isOk()).andReturn();
        return json.readTree(result.getResponse().getContentAsString()).get("id").asText();
    }
    @Test void jwtValidationAndAnonymousDenial() throws Exception {
        mvc.perform(get("/api/me")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/me").header("Authorization","Bearer broken")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+token("employee","wrong",new Date(System.currentTimeMillis()+900000)))).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+token("employee","mediamesh-api",new Date(System.currentTimeMillis()-120000)))).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+token("employee"))).andExpect(status().isOk()).andExpect(jsonPath("$.roles").isEmpty());
    }
    @Test void roleGrantAndRevocationApplyToSameTokenAndAreAudited() throws Exception {
        String admin=token("admin"),employee=token("employee");
        userId(admin);String id=userId(employee);
        mvc.perform(get("/api/assets").header("Authorization","Bearer "+employee)).andExpect(status().isForbidden());
        mvc.perform(put("/api/admin/users/"+id+"/roles").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"roles\":[\"UPLOADER\"]}")).andExpect(status().isForbidden());
        mvc.perform(put("/api/admin/users/"+id+"/roles").header("Authorization","Bearer "+admin).contentType("application/json").content("{\"roles\":[\"UPLOADER\"]}")).andExpect(status().isOk());
        mvc.perform(get("/api/assets").header("Authorization","Bearer "+employee)).andExpect(status().isOk());
        mvc.perform(put("/api/admin/users/"+id+"/roles").header("Authorization","Bearer "+admin).contentType("application/json").content("{\"roles\":[]}")).andExpect(status().isOk());
        mvc.perform(get("/api/assets").header("Authorization","Bearer "+employee)).andExpect(status().isForbidden());
        org.assertj.core.api.Assertions.assertThat(jdbc.queryForObject("SELECT count(*) FROM audit_events WHERE action='REPLACE_ROLES'",Integer.class)).isEqualTo(2);
    }
    @Test void logoutIdleAndAbsoluteExpiryAreEnforced() throws Exception {
        String employee=token("employee");userId(employee);
        jdbc.update("UPDATE api_sessions SET last_seen=clock_timestamp()-interval '31 minutes'");
        mvc.perform(get("/api/me").header("Authorization","Bearer "+employee)).andExpect(status().isUnauthorized());
        jdbc.update("UPDATE api_sessions SET last_seen=clock_timestamp(),started_at=clock_timestamp()-interval '9 hours'");
        mvc.perform(get("/api/me").header("Authorization","Bearer "+employee)).andExpect(status().isUnauthorized());
        jdbc.update("UPDATE api_sessions SET started_at=clock_timestamp(),last_seen=clock_timestamp()");
        mvc.perform(post("/api/logout").header("Authorization","Bearer "+employee)).andExpect(status().isOk());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+employee)).andExpect(status().isUnauthorized());
    }
    @Test void completeAndAccessRespectOwnerAndReadyState() throws Exception {
        String employee=token("employee"),other=token("other");String id=userId(employee),otherId=userId(other);
        jdbc.update("INSERT INTO user_roles VALUES (?::uuid,'UPLOADER'),(?::uuid,'RESEARCHER')",id,otherId);
        when(storage.createUploadUrl(anyString(),anyString())).thenReturn("https://s3.example/upload");
        var response=mvc.perform(post("/api/assets/initiate").header("Authorization","Bearer "+employee).contentType("application/json")
            .content("{\"filename\":\"photo.jpg\",\"contentType\":\"image/jpeg\",\"title\":\"Elephant\"}")).andExpect(status().isOk()).andReturn();
        String asset=json.readTree(response.getResponse().getContentAsString()).get("assetId").asText();
        mvc.perform(get("/api/assets/"+asset).header("Authorization","Bearer "+other)).andExpect(status().isForbidden());
        mvc.perform(post("/api/assets/"+asset+"/complete").header("Authorization","Bearer "+other)).andExpect(status().isForbidden());
        mvc.perform(post("/api/assets/"+asset+"/complete").header("Authorization","Bearer "+employee)).andExpect(status().isAccepted());
        mvc.perform(post("/api/assets/"+asset+"/access-url").header("Authorization","Bearer "+other)).andExpect(status().isConflict());
        jdbc.update("UPDATE assets SET processing_status='READY' WHERE id=?::uuid",asset);
        when(storage.createAccessUrl(anyString(),eq(false))).thenReturn("https://s3.example/preview");
        mvc.perform(post("/api/assets/"+asset+"/access-url").header("Authorization","Bearer "+other)).andExpect(status().isOk()).andExpect(jsonPath("$.expiresInSeconds").value(60));
        mvc.perform(get("/api/assets/"+UUID.randomUUID()).header("Authorization","Bearer "+other)).andExpect(status().isNotFound());
    }

    UUID catalogAsset(String owner) {
        UUID id=UUID.randomUUID();
        jdbc.update("INSERT INTO assets(id,owner_id,s3_key,media_type,title,processing_status) VALUES (?,?::uuid,?,'image','Owner photo','UPLOADING')",id,owner,"assets/"+id);
        return id;
    }
    @Test void everyAssetIdRouteEnforcesItsObjectPolicy() throws Exception {
        String owner=token("owner"),other=token("other-uploader");
        String ownerId=userId(owner),otherId=userId(other);
        jdbc.update("INSERT INTO user_roles VALUES (?::uuid,'UPLOADER'),(?::uuid,'UPLOADER')",ownerId,otherId);
        UUID id=catalogAsset(ownerId);
        mvc.perform(get("/api/assets/"+id).header("Authorization","Bearer "+other)).andExpect(status().isForbidden());
        mvc.perform(put("/api/assets/"+id).header("Authorization","Bearer "+other).contentType("application/json").content("{\"title\":\"Stolen edit\"}")).andExpect(status().isForbidden());
        mvc.perform(post("/api/assets/"+id+"/complete").header("Authorization","Bearer "+other)).andExpect(status().isForbidden());
        mvc.perform(post("/api/assets/"+id+"/access-url").header("Authorization","Bearer "+other)).andExpect(status().isForbidden());
        mvc.perform(post("/api/assets/"+id+"/similar").header("Authorization","Bearer "+other)).andExpect(status().isForbidden());
        verify(storage,never()).verifyUpload(anyString(),anyString());
        verify(storage,never()).createAccessUrl(anyString(),anyBoolean());
        mvc.perform(put("/api/assets/"+id).header("Authorization","Bearer "+owner).contentType("application/json").content("{\"title\":\"Authorized edit\"}")).andExpect(status().isOk()).andExpect(jsonPath("$.title").value("Authorized edit"));
    }
    @Test void researchersMayReadReadyLibraryAssetsButNotPendingAssets() throws Exception {
        String owner=token("owner"),researcher=token("researcher");
        UUID id=catalogAsset(userId(owner));String researcherId=userId(researcher);
        jdbc.update("INSERT INTO user_roles VALUES (?::uuid,'RESEARCHER')",researcherId);
        mvc.perform(get("/api/assets/"+id).header("Authorization","Bearer "+researcher)).andExpect(status().isForbidden());
        mvc.perform(post("/api/assets/"+id+"/access-url").header("Authorization","Bearer "+researcher)).andExpect(status().isConflict());
        mvc.perform(post("/api/assets/"+id+"/similar").header("Authorization","Bearer "+researcher)).andExpect(status().isConflict());
        jdbc.update("UPDATE assets SET processing_status='READY' WHERE id=?",id);
        when(storage.createAccessUrl(anyString(),anyBoolean())).thenReturn("https://example.org/signed");
        when(ml.similar(anyMap())).thenReturn(new com.mediamesh.media.MlSearchClient.Matches(List.of()));
        jdbc.update("UPDATE assets SET generated_description='A tiger standing on grass.' WHERE id=?",id);
        mvc.perform(get("/api/assets/"+id).header("Authorization","Bearer "+researcher))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.generatedDescription").value("A tiger standing on grass."))
                .andExpect(jsonPath("$.objectKey").doesNotExist())
                .andExpect(jsonPath("$.s3Key").doesNotExist());
        mvc.perform(post("/api/assets/"+id+"/access-url").header("Authorization","Bearer "+researcher)).andExpect(status().isOk());
        mvc.perform(post("/api/assets/"+id+"/similar").header("Authorization","Bearer "+researcher)).andExpect(status().isOk());
    }
    @Test void roleTargetIdsCannotBeUsedToEscalatePrivileges() throws Exception {
        String employee=token("employee"),admin=token("admin");
        String employeeId=userId(employee),adminId=userId(admin);
        for(String id:List.of(employeeId,adminId))
            mvc.perform(put("/api/admin/users/"+id+"/roles").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"roles\":[\"ADMIN\"]}")).andExpect(status().isForbidden());
        mvc.perform(put("/api/admin/users/"+UUID.randomUUID()+"/roles").header("Authorization","Bearer "+admin).contentType("application/json").content("{\"roles\":[]}")).andExpect(status().isNotFound());
        mvc.perform(put("/api/admin/users/"+adminId+"/roles").header("Authorization","Bearer "+admin).contentType("application/json").content("{\"roles\":[]}")).andExpect(status().isForbidden());
    }
    @Test void googleRequestsStayBlockedUntilAdminApprovalAndCanCombineRoles() throws Exception {
        String admin=token("admin"),employee=token("employee");userId(admin);String id=userId(employee);
        mvc.perform(post("/api/me/access-request").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"roles\":[\"UPLOADER\",\"RESEARCHER\"]}"))
            .andExpect(status().isCreated()).andExpect(jsonPath("$.requestStatus").value("PENDING")).andExpect(jsonPath("$.roles").isEmpty());
        mvc.perform(get("/api/assets").header("Authorization","Bearer "+employee)).andExpect(status().isForbidden());
        mvc.perform(post("/api/search").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"query\":\"tiger\"}")).andExpect(status().isForbidden());
        mvc.perform(get("/api/admin/access-requests").header("Authorization","Bearer "+employee)).andExpect(status().isForbidden());
        var pending=mvc.perform(get("/api/admin/access-requests").header("Authorization","Bearer "+admin)).andExpect(status().isOk()).andReturn();
        String request=json.readTree(pending.getResponse().getContentAsString()).get(0).get("id").asText();
        mvc.perform(post("/api/me/access-request").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"roles\":[\"UPLOADER\"]}")).andExpect(status().isConflict());
        decision(employee,request,true).andExpect(status().isForbidden());
        decision(admin,request,true).andExpect(status().isNoContent());
        decision(admin,request,true).andExpect(status().isConflict());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+employee)).andExpect(jsonPath("$.roles.length()").value(2)).andExpect(jsonPath("$.requestStatus").value("APPROVED"));
        mvc.perform(get("/api/assets").header("Authorization","Bearer "+employee)).andExpect(status().isOk());
        org.assertj.core.api.Assertions.assertThat(jdbc.queryForObject("SELECT count(*) FROM audit_events WHERE action='APPROVE_ACCESS'",Integer.class)).isOne();
    }
    org.springframework.test.web.servlet.ResultActions decision(String bearer,String request,boolean approve) throws Exception {
        return mvc.perform(post("/api/admin/access-requests/"+request+"/decision").header("Authorization","Bearer "+bearer).contentType("application/json").content("{\"approve\":"+approve+"}"));
    }
    @Test void rejectedRequestsCanBeResubmittedAndAdminCannotBeRequestedOrGranted() throws Exception {
        String admin=token("admin"),employee=token("employee");userId(admin);String id=userId(employee);
        for(String roles:List.of("[]","[\"ADMIN\"]"))
            mvc.perform(post("/api/me/access-request").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"roles\":"+roles+"}")).andExpect(status().isBadRequest());
        mvc.perform(put("/api/admin/users/"+id+"/roles").header("Authorization","Bearer "+admin).contentType("application/json").content("{\"roles\":[\"ADMIN\"]}")).andExpect(status().isForbidden());
        for(int i=0;i<2;i++) {
            mvc.perform(post("/api/me/access-request").header("Authorization","Bearer "+employee).contentType("application/json").content("{\"roles\":[\"RESEARCHER\"]}")).andExpect(status().isCreated());
            String request=jdbc.queryForObject("SELECT id::text FROM access_requests WHERE status='PENDING'",String.class);
            decision(admin,request,false).andExpect(status().isNoContent());
            mvc.perform(get("/api/me").header("Authorization","Bearer "+employee)).andExpect(jsonPath("$.roles").isEmpty()).andExpect(jsonPath("$.requestStatus").value("REJECTED"));
        }
    }
    @Test void passwordSignInAndUnverifiedGoogleEmailAreRejectedEvenForAdmin() throws Exception {
        for(String claim:List.of("identity_provider","email_verified")) {
            var original=SignedJWT.parse(token("admin")).getJWTClaimsSet();
            var claims=new JWTClaimsSet.Builder(original).claim(claim,claim.equals("email_verified")?false:"other").build();
            var jwt=new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("test").build(),claims);
            jwt.sign(new RSASSASigner(key));
            mvc.perform(get("/api/me").header("Authorization","Bearer "+jwt.serialize())).andExpect(status().isUnauthorized());
        }
        mvc.perform(get("/api/me").header("Authorization","Bearer "+token("admin"))).andExpect(jsonPath("$.primaryAdmin").value(true));
    }
    @Test void videoPreviewsUseThePlaybackCopyButDownloadsUseTheOriginal() throws Exception {
        String owner=token("owner"),researcher=token("researcher");
        String ownerId=userId(owner),researcherId=userId(researcher);
        jdbc.update("INSERT INTO user_roles VALUES (?::uuid,'RESEARCHER')",researcherId);
        UUID id=UUID.randomUUID(),plain=UUID.randomUUID();
        jdbc.update("INSERT INTO assets(id,owner_id,s3_key,media_type,title,processing_status,playback_key) VALUES (?,?::uuid,?,'video','Clip','READY',?)",
            id,ownerId,"assets/o/"+id+"/source/clip.mov","assets/o/"+id+"/playback/web.mp4");
        jdbc.update("INSERT INTO assets(id,owner_id,s3_key,media_type,title,processing_status) VALUES (?,?::uuid,?,'video','Old clip','READY')",
            plain,ownerId,"assets/o/"+plain+"/source/old.mp4");
        when(storage.createAccessUrl(anyString(),anyBoolean())).thenReturn("https://example.org/signed");
        mvc.perform(post("/api/assets/"+id+"/access-url").header("Authorization","Bearer "+researcher)).andExpect(status().isOk());
        verify(storage).createAccessUrl("assets/o/"+id+"/playback/web.mp4",false);
        mvc.perform(post("/api/assets/"+id+"/access-url?download=true").header("Authorization","Bearer "+researcher)).andExpect(status().isOk());
        verify(storage).createAccessUrl("assets/o/"+id+"/source/clip.mov",true);
        mvc.perform(post("/api/assets/"+plain+"/access-url").header("Authorization","Bearer "+researcher)).andExpect(status().isOk());
        verify(storage).createAccessUrl("assets/o/"+plain+"/source/old.mp4",false);
    }
    org.springframework.test.web.servlet.ResultActions deleteUser(String bearer,String id) throws Exception {
        return mvc.perform(delete("/api/admin/users/"+id).header("Authorization","Bearer "+bearer));
    }
    @Test void deletingAUserRemovesLoginRolesAndSessionsButKeepsTheirMedia() throws Exception {
        String admin=token("admin"),uploader=token("uploader-subject");
        String adminId=userId(admin),uploaderId=userId(uploader);
        jdbc.update("INSERT INTO user_roles VALUES (?::uuid,'UPLOADER')",uploaderId);
        UUID asset=catalogAsset(uploaderId);
        deleteUser(uploader,adminId).andExpect(status().isForbidden());
        deleteUser(admin,adminId).andExpect(status().isConflict());
        deleteUser(admin,uploaderId).andExpect(status().isNoContent());
        verify(keycloak).remove("uploader-subject");
        mvc.perform(get("/api/me").header("Authorization","Bearer "+uploader)).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+token("uploader-subject"))).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/admin/users").header("Authorization","Bearer "+admin)).andExpect(jsonPath("$[?(@.id=='"+uploaderId+"')]").isEmpty());
        deleteUser(admin,uploaderId).andExpect(status().isNotFound());
        org.assertj.core.api.Assertions.assertThat(jdbc.queryForObject("SELECT count(*) FROM user_roles WHERE user_id=?::uuid",Integer.class,uploaderId)).isZero();
        org.assertj.core.api.Assertions.assertThat(jdbc.queryForObject("SELECT count(*) FROM assets WHERE id=?",Integer.class,asset)).isOne();
        org.assertj.core.api.Assertions.assertThat(jdbc.queryForObject("SELECT count(*) FROM audit_events WHERE action='DELETE_USER'",Integer.class)).isOne();
    }
    @Test void identityServiceFailureLeavesTheUserUntouched() throws Exception {
        String admin=token("admin"),employee=token("employee");userId(admin);String employeeId=userId(employee);
        doThrow(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_GATEWAY,"Identity service unavailable"))
            .when(keycloak).remove("employee");
        deleteUser(admin,employeeId).andExpect(status().isBadGateway());
        mvc.perform(get("/api/me").header("Authorization","Bearer "+employee)).andExpect(status().isOk());
    }
}
