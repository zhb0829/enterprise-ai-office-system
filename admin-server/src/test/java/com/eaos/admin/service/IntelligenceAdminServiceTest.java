package com.eaos.admin.service;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.entity.ArticleCluster;
import com.eaos.admin.entity.CollectedArticle;
import com.eaos.admin.entity.CollectionTaskLog;
import com.eaos.admin.entity.IntelligenceReport;
import com.eaos.admin.entity.SourceConfig;
import com.eaos.admin.mapper.ArticleClusterMapper;
import com.eaos.admin.mapper.CollectedArticleMapper;
import com.eaos.admin.mapper.CollectionTaskLogMapper;
import com.eaos.admin.mapper.IntelligenceReportMapper;
import com.eaos.admin.mapper.SourceConfigMapper;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestTemplate;

@ExtendWith(MockitoExtension.class)
class IntelligenceAdminServiceTest {

  @Mock private SourceConfigMapper sourceConfigMapper;
  @Mock private CollectionTaskLogMapper taskLogMapper;
  @Mock private CollectedArticleMapper articleMapper;
  @Mock private ArticleClusterMapper clusterMapper;
  @Mock private IntelligenceReportMapper reportMapper;
  @Mock private RestTemplate restTemplate;
  @Mock private AiServiceProperties aiProperties;

  @InjectMocks private IntelligenceAdminService service;

  @Test
  void listArticlesDoesNotOrderAggregateCountQuery() {
    AtomicReference<String> countSql = new AtomicReference<>();
    when(articleMapper.selectCount(any()))
        .thenAnswer(
            invocation -> {
              Wrapper<?> wrapper = invocation.getArgument(0);
              countSql.set(wrapper.getSqlSegment());
              return 0L;
            });
    when(articleMapper.selectList(any())).thenReturn(List.of());

    service.listArticles(null, "", null, 1, 20);

    ArgumentCaptor<Wrapper<CollectedArticle>> listCaptor = ArgumentCaptor.forClass(Wrapper.class);
    verify(articleMapper).selectList(listCaptor.capture());

    assertFalse(countSql.get().contains("ORDER BY"));
    assertTrue(listCaptor.getValue().getSqlSegment().contains("ORDER BY collected_at DESC"));
  }
}
