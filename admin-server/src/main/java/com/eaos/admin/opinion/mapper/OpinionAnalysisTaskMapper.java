package com.eaos.admin.opinion.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.eaos.admin.opinion.entity.OpinionAnalysisTask;
import java.time.LocalDateTime;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface OpinionAnalysisTaskMapper extends BaseMapper<OpinionAnalysisTask> {

  @Select(
      """
            WITH recovered AS (
                UPDATE opinion_analysis_task
                   SET status = 'queued', worker = '', claimed_at = NULL,
                       updated_at = NOW()
                 WHERE status = 'analyzing'
                   AND claimed_at IS NOT NULL
                   AND claimed_at < #{staleBefore}
            ), candidate AS (
                SELECT id
                  FROM opinion_analysis_task
                 WHERE status IN ('queued', 'failed')
                   AND retry_count < #{maxRetries}
                   AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                 ORDER BY id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            ), claimed AS (
                UPDATE opinion_analysis_task t
                   SET status = 'analyzing', worker = #{worker},
                       claimed_at = NOW(), updated_at = NOW()
                  FROM candidate c
                 WHERE t.id = c.id
                RETURNING t.*
            )
            SELECT * FROM claimed
            """)
  OpinionAnalysisTask claimNext(
      @Param("worker") String worker,
      @Param("staleBefore") LocalDateTime staleBefore,
      @Param("maxRetries") int maxRetries);
}
