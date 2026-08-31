package com.eaos.admin.meeting.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.eaos.admin.meeting.dto.ConferenceSaveRequest;
import com.eaos.admin.meeting.dto.MaterialLinkRequest;
import com.eaos.admin.meeting.entity.Conference;
import com.eaos.admin.meeting.mapper.ConferenceMapper;
import com.eaos.admin.meeting.mapper.ConferenceMaterialMapper;
import com.eaos.admin.meeting.mapper.ConferenceMediaMapper;
import com.eaos.admin.meeting.mapper.ConferenceReportMapper;
import com.eaos.admin.meeting.mapper.ConferenceTaskMapper;
import com.eaos.admin.meeting.mapper.KnowledgeCardMapper;
import com.eaos.admin.meeting.support.MeetingStorageService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MeetingConferenceServiceTest {

    @Mock
    private ConferenceMapper conferenceMapper;
    @Mock
    private ConferenceMaterialMapper materialMapper;
    @Mock
    private ConferenceReportMapper reportMapper;
    @Mock
    private KnowledgeCardMapper cardMapper;
    @Mock
    private ConferenceTaskMapper taskMapper;
    @Mock
    private ConferenceMediaMapper mediaMapper;
    @Mock
    private MeetingStorageService storageService;
    @Mock
    private MeetingTaskService taskService;

    @InjectMocks
    private MeetingConferenceService service;

    @Test
    void createUsesDraftStateAndDefaultCategory() {
        ConferenceSaveRequest request = new ConferenceSaveRequest();
        request.setName("2026 行业发展论坛");

        Conference result = service.create(request);

        assertEquals("行业会议", result.getCategory());
        assertEquals("draft", result.getStatus());
        assertEquals(false, result.getArchived());
    }

    @Test
    void addLinkRejectsExactDuplicateUrl() {
        Conference conference = new Conference();
        conference.setId(1L);
        conference.setStatus("draft");
        conference.setArchived(false);
        when(conferenceMapper.selectById(1L)).thenReturn(conference);
        when(materialMapper.selectCount(any(Wrapper.class))).thenReturn(0L, 1L);

        MaterialLinkRequest request = new MaterialLinkRequest();
        request.setUrl("https://example.com/conference");

        IllegalArgumentException error = assertThrows(
                IllegalArgumentException.class,
                () -> service.addLink(1L, request));
        assertEquals("该资料链接已添加", error.getMessage());
    }
}
