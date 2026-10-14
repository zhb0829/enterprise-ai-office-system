package com.eaos.admin.opinion.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.eaos.admin.opinion.entity.OpinionArticle;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface OpinionArticleMapper extends BaseMapper<OpinionArticle> {
  @Select("SELECT id FROM opinion_article WHERE id = #{id} FOR UPDATE")
  Long lockArticle(@Param("id") Long id);
}
