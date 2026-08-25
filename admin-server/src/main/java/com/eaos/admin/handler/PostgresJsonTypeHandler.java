package com.eaos.admin.handler;

import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import org.apache.ibatis.type.JdbcType;
import org.postgresql.util.PGobject;

import java.lang.reflect.Field;
import java.sql.PreparedStatement;
import java.sql.SQLException;

/** Binds JSON values as PostgreSQL JSON instead of VARCHAR. */
public class PostgresJsonTypeHandler extends JacksonTypeHandler {
    public PostgresJsonTypeHandler(Class<?> type) {
        super(type);
    }

    public PostgresJsonTypeHandler(Class<?> type, Field field) {
        super(type, field);
    }

    @Override
    public void setNonNullParameter(PreparedStatement ps, int index, Object parameter, JdbcType jdbcType)
            throws SQLException {
        PGobject value = new PGobject();
        value.setType("json");
        value.setValue(toJson(parameter));
        ps.setObject(index, value);
    }
}
