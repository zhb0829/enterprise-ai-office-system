package com.eaos.admin.security;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.eaos.admin.entity.SysUser;
import com.eaos.admin.mapper.SysUserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class UserDetailsServiceImpl implements UserDetailsService {

  private final SysUserMapper sysUserMapper;

  @Override
  public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
    SysUser user =
        sysUserMapper.selectOne(
            new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, username));
    if (user == null) {
      throw new UsernameNotFoundException("用户不存在：" + username);
    }
    return new LoginUser(
        user.getId(),
        user.getUsername(),
        user.getPassword(),
        user.getNickname(),
        user.getRole(),
        user.getTenantId(),
        user.getEnabled());
  }
}
