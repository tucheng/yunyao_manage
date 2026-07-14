window.userPage = 1;

window.loadUsers = function(p) {
  if (p !== undefined) window.userPage = p;
  var searchEl = document.getElementById('userSearch');
  var q = searchEl ? searchEl.value.trim() : '';
  var url = '/admin/users?page=' + window.userPage + '&page_size=20';
  if (q) url += '&q=' + encodeURIComponent(q);

  api(url).then(function(res) {
    var users = res.results || [];
    var tbody = document.getElementById('userTableBody');
    var html = '';
    users.forEach(function(u) {
      var levelBadge = u.level_name === 'VIP大师' ? 'badge-admin' : 'badge-neutral';
      html += '<tr>' +
        '<td>' + u.id + '</td>' +
        '<td><strong>' + esc(u.nickname || '?') + '</strong></td>' +
        '<td style="color:#888;font-size:12px">' + esc(u.username || '-') + '</td>' +
        '<td><span class="badge ' + levelBadge + '">' + esc(u.level_name) + '</span></td>' +
        '<td>' + (u.is_admin ? '<span class="badge badge-admin">是</span>' : '否') + '</td>' +
        '<td>' + (u.recipe_count || 0) + '</td>' +
        '<td>' + (u.work_count || 0) + '</td>' +
        '<td>' + (u.is_muted ? '<span class="tag-muted">🚫 禁言</span>' : '<span style="color:#27ae60">正常</span>') + '</td>' +
        '<td><button class="btn btn-sm" onclick="window.showUserModal(' + u.id + ')">编辑</button></td>' +
        '</tr>';
    });
    if (users.length === 0) {
      html = '<tr><td colspan="9" style="text-align:center;color:#999;padding:24px">暂无用户</td></tr>';
    }
    tbody.innerHTML = html;

    var totalPages = Math.ceil(res.total / 20);
    document.getElementById('userPagination').innerHTML =
      '<button class="btn btn-sm" onclick="window.loadUsers(' + (window.userPage - 1) + ')" ' + (window.userPage <= 1 ? 'disabled' : '') + '>‹</button>' +
      '<span>第 ' + res.page + '/' + totalPages + ' 页 (共 ' + res.total + ' 人)</span>' +
      '<button class="btn btn-sm" onclick="window.loadUsers(' + (window.userPage + 1) + ')" ' + (window.userPage >= totalPages ? 'disabled' : '') + '>›</button>';
  }).catch(function(err) {
    toast('加载失败: ' + (err.message || err), 'error');
  });
};

window.showUserModal = function(userId) {
  api('/admin/users/' + userId).then(function(u) {
    document.getElementById('userModalTitle').textContent = '编辑用户 - ' + u.nickname;
    document.getElementById('userEditNickname').textContent = u.nickname + ' (ID:' + u.id + ')';
    document.getElementById('userEditMuted').checked = u.is_muted;
    document.getElementById('userEditAdmin').checked = u.is_admin;
    var sel = document.getElementById('userEditLevel');
    sel.innerHTML = '';
    api('/admin/levels').then(function(levels) {
      levels.forEach(function(l) {
        var opt = document.createElement('option');
        opt.value = l.id;
        opt.textContent = l.name;
        if (l.id === u.level_id) opt.selected = true;
        sel.appendChild(opt);
      });
    });
    document.getElementById('userModal').dataset.userId = userId;
    window.openModal('userModal');
  }).catch(function(err) {
    toast('获取用户信息失败: ' + (err.message || err), 'error');
  });
};

window.saveUser = function() {
  var userId = document.getElementById('userModal').dataset.userId;
  var data = {
    level_id: parseInt(document.getElementById('userEditLevel').value),
    is_muted: document.getElementById('userEditMuted').checked,
    is_admin: document.getElementById('userEditAdmin').checked
  };
  api('/admin/users/' + userId, {
    method: 'PUT',
    body: JSON.stringify(data)
  }).then(function() {
    toast('用户已更新');
    window.closeModal('userModal');
    window.loadUsers();
  }).catch(function(e) {
    toast(e.message || '保存失败', 'error');
  });
};

window.loadUsers();
