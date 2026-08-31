package com.eaos.admin.meeting.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.eaos.admin.meeting.entity.ConferenceReport;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ConferenceReportMapper extends BaseMapper<ConferenceReport> {

    @Select("SELECT COALESCE(MAX(version), 0) FROM conference_report WHERE conference_id = #{conferenceId}")
    int maxVersion(@Param("conferenceId") Long conferenceId);
}
