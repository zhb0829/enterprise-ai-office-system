package com.eaos.admin;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.eaos.admin.entity.SysUser;
import com.eaos.admin.mapper.SysUserMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.LocalDateTime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * 认证链路集成测试（Q12）：真实 PostgreSQL + Flyway 迁移， 覆盖 登录 → access token 访问 → refresh 轮换 → 旧 token 吊销 → 登出。
 *
 * <p>数据库双模式： - 默认：Testcontainers 启动 pgvector/pg16（CI 环境） - 设置 EAOS_TEST_DB_URL 时连接外部测试库。
 */
@SpringBootTest
@AutoConfigureMockMvc
@DisabledOnOs(value = OS.WINDOWS, disabledReason = "Windows 上的 Docker/Testcontainers 环境不作为此集成测试运行位")
class AuthFlowIntegrationTest {

  private static final String EXTERNAL_URL = System.getenv("EAOS_TEST_DB_URL");

  static final PostgreSQLContainer<?> POSTGRES = EXTERNAL_URL == null ? startContainer() : null;

  private static PostgreSQLContainer<?> startContainer() {
    PostgreSQLContainer<?> container = new PostgreSQLContainer<>("pgvector/pgvector:pg16");
    container.start();
    return container;
  }

  // 密钥 fail-fast 校验（Q5）需要真实密钥值
  @DynamicPropertySource
  static void registerProperties(DynamicPropertyRegistry registry) {
    registry.add("eaos.jwt.secret", () -> "it-jwt-secret-0123456789abcdef0123456789abcdef");
    registry.add("eaos.ai.internal-token", () -> "it-ai-token-0123456789abcdef");
    registry.add("eaos.opinion.internal-token", () -> "it-opinion-token-0123456789abcdef");
    registry.add("eaos.meeting.internal-token", () -> "it-meeting-token-0123456789abcdef");
    if (EXTERNAL_URL != null && !EXTERNAL_URL.isBlank()) {
      registry.add("spring.datasource.url", () -> EXTERNAL_URL);
    } else {
      registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
      registry.add("spring.datasource.username", POSTGRES::getUsername);
      registry.add("spring.datasource.password", POSTGRES::getPassword);
    }
  }

  @Autowired MockMvc mockMvc;
  @Autowired ObjectMapper objectMapper;
  @Autowired SysUserMapper sysUserMapper;
  @Autowired PasswordEncoder passwordEncoder;

  @BeforeEach
  void seedUser() {
    Long count =
        sysUserMapper.selectCount(
            new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, "tester"));
    if (count == null || count == 0L) {
      SysUser user = new SysUser();
      user.setUsername("tester");
      user.setPassword(passwordEncoder.encode("Tester1234"));
      user.setNickname("集成测试用户");
      user.setRole("USER");
      user.setEnabled(true);
      user.setMustChangePassword(false);
      user.setCreatedAt(LocalDateTime.now());
      user.setUpdatedAt(LocalDateTime.now());
      sysUserMapper.insert(user);
    }
  }

  private JsonNode postJson(String url, String body) throws Exception {
    MvcResult result =
        mockMvc
            .perform(post(url).contentType("application/json").content(body))
            .andExpect(status().isOk())
            .andReturn();
    return objectMapper.readTree(result.getResponse().getContentAsString());
  }

  @Test
  void loginRefreshRevokeLogoutFlow() throws Exception {
    // 未认证访问受保护接口 → 401
    mockMvc.perform(get("/api/notifications/unread-count")).andExpect(status().isUnauthorized());

    // 登录
    JsonNode login =
        postJson("/api/auth/login", "{\"username\":\"tester\",\"password\":\"Tester1234\"}");
    assertEquals(0, login.get("code").asInt());
    String token = login.at("/data/token").asText();
    String refresh = login.at("/data/refreshToken").asText();
    assertTrue(!token.isBlank() && !refresh.isBlank());

    // 携带 access token 访问 → 200
    mockMvc
        .perform(get("/api/notifications/unread-count").header("Authorization", "Bearer " + token))
        .andExpect(status().isOk());

    // refresh 轮换：返回新的 access/refresh
    JsonNode rotated = postJson("/api/auth/refresh", "{\"refreshToken\":\"" + refresh + "\"}");
    assertEquals(0, rotated.get("code").asInt());
    String newRefresh = rotated.at("/data/refreshToken").asText();

    // 旧 refresh 已吊销 → 业务码 401
    JsonNode revoked = postJson("/api/auth/refresh", "{\"refreshToken\":\"" + refresh + "\"}");
    assertEquals(401, revoked.get("code").asInt());

    // 登出吊销新 refresh，再次 refresh 失败
    postJson("/api/auth/logout", "{\"refreshToken\":\"" + newRefresh + "\"}");
    JsonNode afterLogout =
        postJson("/api/auth/refresh", "{\"refreshToken\":\"" + newRefresh + "\"}");
    assertEquals(401, afterLogout.get("code").asInt());
  }

  @Test
  void wrongPasswordIsRejected() throws Exception {
    JsonNode response =
        postJson("/api/auth/login", "{\"username\":\"tester\",\"password\":\"wrong-password\"}");
    assertEquals(401, response.get("code").asInt());
  }
}
