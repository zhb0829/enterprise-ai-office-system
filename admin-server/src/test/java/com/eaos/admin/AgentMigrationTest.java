package com.eaos.admin;

import static org.junit.jupiter.api.Assertions.*;

import java.sql.DriverManager;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/** Run only against an explicitly supplied disposable database. */
@EnabledIfEnvironmentVariable(named = "P1_TEST_JDBC_URL", matches = ".+")
class AgentMigrationTest {
  @Test
  void baselineAndOpinionUpgradeSupportRealPostgresAndAreIdempotent() throws Exception {
    String url = System.getenv("P1_TEST_JDBC_URL");
    String user = System.getenv("P1_TEST_DB_USER");
    String password = System.getenv("P1_TEST_DB_PASSWORD");
    var flyway = Flyway.configure().dataSource(url, user, password).load();
    assertEquals(4, flyway.migrate().migrationsExecuted);
    assertEquals(0, flyway.migrate().migrationsExecuted);
    try (var connection = DriverManager.getConnection(url, user, password);
        var statement = connection.createStatement()) {
      var columns = statement.executeQuery(
          "SELECT column_name FROM information_schema.columns WHERE table_name='opinion_event'");
      var names = new java.util.HashSet<String>();
      while (columns.next()) names.add(columns.getString(1));
      assertTrue(names.containsAll(java.util.Set.of(
          "event_key", "subjects", "timeline", "trend_direction", "risk_score", "review_required")));
      var indexes = statement.executeQuery(
          "SELECT count(*) FROM pg_indexes WHERE indexname='uq_opinion_event_key'");
      assertTrue(indexes.next());
      assertEquals(1, indexes.getInt(1));
    }
  }
}
