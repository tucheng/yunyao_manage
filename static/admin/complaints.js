window.complaintPage = 1;
window.currentComplaintId = null;

window.complaintDate = function(value) {
  if (!value) return '-';
  var date = new Date(value);
  return isNaN(date.getTime()) ? esc(value) : date.toLocaleString('zh-CN', { hour12: false });
};

window.complaintImages = function(value) {
  if (!value) return [];
  return (Array.isArray(value) ? value : String(value).split(',')).map(function(item) {
    try {
      var url = new URL(String(item).trim(), window.location.origin);
      return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
    } catch (_) {
      return '';
    }
  }).filter(Boolean);
};

window.complaintFilterUrl = function(page) {
  var params = new URLSearchParams({ page: String(page || 1), page_size: '20' });
  var fields = [
    ['complaintKeyword', 'q'], ['complaintAnswered', 'answered'], ['complaintResolved', 'resolved'],
    ['complaintClosed', 'closed'], ['complaintDateFrom', 'date_from'], ['complaintDateTo', 'date_to']
  ];
  fields.forEach(function(pair) {
    var el = document.getElementById(pair[0]);
    if (el && el.value !== '') params.set(pair[1], el.value);
  });
  return '/admin/complaints?' + params.toString();
};

window.loadComplaints = function(page) {
  window.complaintPage = page || window.complaintPage || 1;
  api(window.complaintFilterUrl(window.complaintPage)).then(function(res) {
    var rows = res.results || [];
    var html = rows.map(function(item) {
      var owner = item.user || {};
      return '<tr>' +
        '<td><div class="complaint-summary">' + esc(item.content || '-') + '</div></td>' +
        '<td class="complaint-user"><strong>' + esc(owner.nickname || owner.username || ('用户 ' + item.user_id)) + '</strong><small>' + esc(owner.username || ('ID: ' + item.user_id)) + '</small></td>' +
        '<td style="white-space:nowrap;color:#777;font-size:12px">' + window.complaintDate(item.created_at) + '</td>' +
        '<td><span class="status-pill ' + (item.is_answered ? 'status-yes' : 'status-no') + '">' + (item.is_answered ? '已答复' : '未答复') + '</span></td>' +
        '<td><span class="status-pill ' + (item.is_resolved ? 'status-yes' : 'status-no') + '">' + (item.is_resolved ? '已解决' : '未解决') + '</span></td>' +
        '<td><span class="status-pill ' + (item.is_closed ? 'status-closed' : 'status-open') + '">' + (item.is_closed ? '已关闭' : '未关闭') + '</span></td>' +
        '<td style="white-space:nowrap"><button class="btn btn-sm" onclick="window.openComplaintDetail(' + item.id + ')">详情 / 答复</button> ' +
        '<button class="btn btn-sm" onclick="window.toggleComplaintClosed(' + item.id + ',' + (!item.is_closed) + ')">' + (item.is_closed ? '重新打开' : '关闭') + '</button></td>' +
        '</tr>';
    }).join('');
    if (!rows.length) html = '<tr><td colspan="7" style="text-align:center;color:#999;padding:28px">没有符合条件的投诉建议</td></tr>';
    document.getElementById('complaintTableBody').innerHTML = html;

    var totalPages = Math.max(1, Math.ceil(res.total / res.page_size));
    document.getElementById('complaintPagination').innerHTML =
      '<button class="btn btn-sm" onclick="window.loadComplaints(' + (window.complaintPage - 1) + ')" ' + (window.complaintPage <= 1 ? 'disabled' : '') + '>‹</button>' +
      '<span>第 ' + res.page + '/' + totalPages + ' 页（共 ' + res.total + ' 条）</span>' +
      '<button class="btn btn-sm" onclick="window.loadComplaints(' + (window.complaintPage + 1) + ')" ' + (window.complaintPage >= totalPages ? 'disabled' : '') + '>›</button>';
  }).catch(function(err) { toast('加载投诉列表失败：' + (err.message || err), 'error'); });
};

window.renderComplaintDetail = function(item) {
  window.currentComplaintId = item.id;
  var owner = item.user || {};
  var images = window.complaintImages(item.images);
  var replies = item.replies || [];
  var imageHtml = images.length ? '<div class="complaint-images">' + images.map(function(src) {
    return '<a href="' + escAttr(src) + '" target="_blank" rel="noopener noreferrer"><img src="' + escAttr(src) + '" alt="投诉图片"></a>';
  }).join('') + '</div>' : '';
  var replyHtml = replies.length ? replies.map(function(reply) {
    return '<div class="reply-card"><small>' + esc(reply.sender_name || '管理员') + ' · ' + window.complaintDate(reply.created_at) + '</small><div style="white-space:pre-wrap;line-height:1.6">' + esc(reply.content || '') + '</div></div>';
  }).join('') : '<div style="padding:12px;color:#999;background:#fafafa;border-radius:6px">尚未答复</div>';
  var statuses = '<span class="status-pill ' + (item.is_answered ? 'status-yes' : 'status-no') + '">' + (item.is_answered ? '已答复' : '未答复') + '</span> ' +
    '<span class="status-pill ' + (item.is_resolved ? 'status-yes' : 'status-no') + '">' + (item.is_resolved ? '已解决' : '未解决') + '</span> ' +
    '<span class="status-pill ' + (item.is_closed ? 'status-closed' : 'status-open') + '">' + (item.is_closed ? '已关闭' : '未关闭') + '</span>';

  document.getElementById('complaintDetailBody').innerHTML =
    '<div class="complaint-detail-head"><div><h3>投诉建议 #' + item.id + '</h3><div style="margin-top:8px">' + statuses + '</div></div>' +
    '<button class="btn btn-sm" onclick="window.toggleComplaintClosed(' + item.id + ',' + (!item.is_closed) + ',true)">' + (item.is_closed ? '重新打开' : '设为关闭') + '</button></div>' +
    '<div class="complaint-detail-meta">提问人：' + esc(owner.nickname || owner.username || ('用户 ' + item.user_id)) + '　·　' + window.complaintDate(item.created_at) + '</div>' +
    '<div class="complaint-detail-content">' + esc(item.content || '') + '</div>' + imageHtml +
    '<div class="reply-thread"><h3>沟通记录</h3>' + replyHtml + '</div>' +
    '<div class="reply-editor"><h3>添加答复</h3><textarea id="complaintReplyText" maxlength="1000" placeholder="输入本次答复内容；用户标记未解决后，可继续在这里追加沟通。"></textarea>' +
    '<div style="text-align:right;margin-top:8px"><button class="btn btn-primary" id="complaintReplyButton" onclick="window.submitComplaintReply()">发送答复</button></div></div>';
};

window.openComplaintDetail = function(id) {
  api('/admin/complaints/' + id).then(function(item) {
    window.renderComplaintDetail(item);
    openModal('complaintDetailModal');
  }).catch(function(err) { toast('加载详情失败：' + (err.message || err), 'error'); });
};

window.submitComplaintReply = function() {
  var textarea = document.getElementById('complaintReplyText');
  var content = textarea ? textarea.value.trim() : '';
  if (!content) return toast('请输入答复内容', 'error');
  var button = document.getElementById('complaintReplyButton');
  button.disabled = true;
  api('/admin/complaints/' + window.currentComplaintId + '/replies', {
    method: 'POST', body: JSON.stringify({ content: content })
  }).then(function(item) {
    toast('答复已发送');
    window.renderComplaintDetail(item);
    window.loadComplaints(window.complaintPage);
  }).catch(function(err) {
    button.disabled = false;
    toast(err.message || '答复失败', 'error');
  });
};

window.toggleComplaintClosed = function(id, closed, keepModal) {
  api('/admin/complaints/' + id + '/closed', {
    method: 'PUT', body: JSON.stringify({ closed: closed })
  }).then(function(item) {
    toast(closed ? '已设为关闭' : '已重新打开');
    window.loadComplaints(window.complaintPage);
    if (keepModal) window.renderComplaintDetail(item);
  }).catch(function(err) { toast(err.message || '更新关闭状态失败', 'error'); });
};

window.loadComplaints(1);
