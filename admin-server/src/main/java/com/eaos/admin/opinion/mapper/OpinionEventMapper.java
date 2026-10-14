package com.eaos.admin.opinion.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.eaos.admin.opinion.entity.OpinionEvent;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface OpinionEventMapper extends BaseMapper<OpinionEvent> {
  @Select("SELECT id FROM opinion_monitor WHERE id = #{monitorId} FOR UPDATE")
  Long lockMonitor(@Param("monitorId") Long monitorId);
}
