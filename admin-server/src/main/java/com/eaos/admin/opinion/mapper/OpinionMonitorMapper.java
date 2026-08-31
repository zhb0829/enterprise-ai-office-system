package com.eaos.admin.opinion.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface OpinionMonitorMapper extends BaseMapper<OpinionMonitor> {
  @Select("SELECT * FROM opinion_monitor WHERE id = #{id} FOR UPDATE")
  OpinionMonitor selectByIdForUpdate(@Param("id") Long id);
}
