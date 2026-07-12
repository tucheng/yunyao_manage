window.redeemPage = 1;

window.loadRedeemCodes = function(p) {
  if (p !== undefined) window.redeemPage = p;
  api('/redeem/admin/codes?page=' + window.redeemPage + '&page_size=20')
    .then(function(data) {
      var list = data.items || data.data || [];
      var total = data.total || list.length;
      var totalPages = Math.ceil(total / 20) || 1;

      document.getElementById('redeemStats').textContent = '共 ' + total + ' 个';

      var tbody = document.getElementById('redeemTableBody');
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#999;padding:30px">暂无兑换码</td></tr>';
      } else {
        tbody.innerHTML = list.map(function(code) {
          var logs = code.logs || [];
          var usersHtml = logs.map(function(l) { return esc(l.user || '-'); }).join('<br>') || '-';
          var beforeHtml = logs.map(function(l) { return l.before_expiry ? l.before_expiry.slice(0, 16).replace('T', ' ') : '-'; }).join('<br>') || '-';
          var afterHtml = logs.map(function(l) { return l.after_expiry ? l.after_expiry.slice(0, 16).replace('T', ' ') : '-'; }).join('<br>') || '-';
          var statusHtml = code.is_active ? '<span style="color:#27ae60">有效</span>' : '<span style="color:#999">已停用</span>';
          return '<tr>' +
            '<td>' + code.id + '</td>' +
            '<td><code style="font-size:14px;letter-spacing:1px;font-weight:600">' + esc(code.code) + '</code></td>' +
            '<td>' + code.days + ' 天</td>' +
            '<td>' + code.current_uses + '/' + code.max_uses + '</td>' +
            '<td>' + usersHtml + '</td>' +
            '<td style="font-size:12px;color:#888;white-space:nowrap">' + beforeHtml + '</td>' +
            '<td style="font-size:12px;color:#27ae60;white-space:nowrap">' + afterHtml + '</td>' +
            '<td>' + statusHtml + '</td>' +
            '<td style="color:#888;font-size:12px">' + esc(code.created_at || '') + '</td>' +
            '</tr>';
        }).join('');
      }

      var pag = document.getElementById('redeemPagination');
      pag.innerHTML =
        '<button class="btn btn-sm" onclick="window.loadRedeemCodes(' + (window.redeemPage - 1) + ')" ' + (window.redeemPage <= 1 ? 'disabled' : '') + '>‹</button>' +
        '<span>第 ' + data.page + '/' + totalPages + ' 页 (共 ' + total + ' 个码)</span>' +
        '<button class="btn btn-sm" onclick="window.loadRedeemCodes(' + (window.redeemPage + 1) + ')" ' + (window.redeemPage >= totalPages ? 'disabled' : '') + '>›</button>';
    })
    .catch(function(e) { toast('加载失败: ' + (e.message || e), 'error'); });
};

window.generateCodes = function() {
  var count = parseInt(document.getElementById('redeemCount').value) || 1;
  var days = parseInt(document.getElementById('redeemDays').value) || 30;
  var maxUses = parseInt(document.getElementById('redeemMaxUses').value) || 1;
  var el = document.getElementById('generateResult');
  el.innerHTML = '生成中...';
  el.style.display = 'block';
  api('/redeem/admin/generate', {
    method: 'POST',
    body: JSON.stringify({ count: count, days: days, max_uses: maxUses })
  }).then(function(d) {
    el.innerHTML = '✅ 成功生成 ' + d.count + ' 个兑换码：<br><code style="font-size:13px">' + d.codes.join('</code>、<code>') + '</code>';
    window.loadRedeemCodes(1);
  }).catch(function(e) {
    el.innerHTML = '';
    toast('生成失败: ' + (e.message || e), 'error');
  });
};

window.loadRedeemCodes(1);
