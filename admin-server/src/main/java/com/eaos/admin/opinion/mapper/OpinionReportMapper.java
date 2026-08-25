package com.eaos.admin.opinion.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.eaos.admin.opinion.entity.OpinionReport;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface OpinionReportMapper extends BaseMapper<OpinionReport> {
    @Select("SELECT * FROM opinion_report WHERE monitor_id = #{monitorId} AND period = #{period} ORDER BY version DESC LIMIT 1 FOR UPDATE")
    OpinionReport selectLatestForUpdate(@Param("monitorId") Long monitorId, @Param("period") String period);
}
