window.loadSystemSettings = function() {
  api('/admin/paid-enabled').then(function(s) {
    document.getElementById('paidEnabledToggle').checked = s.paid_enabled === true;
  }).catch(function(e) {
    toast('加载失败: ' + (e.message || e), 'error');
  });
};

window.togglePaidEnabled = function() {
  var checked = document.getElementById('paidEnabledToggle').checked;
  api('/admin/paid-enabled', {
    method: 'PUT',
    body: JSON.stringify({ paid_enabled: checked })
  }).then(function() {
    toast(checked ? '付费功能已开启' : '付费功能已关闭');
  }).catch(function(e) {
    document.getElementById('paidEnabledToggle').checked = !checked;
    toast(e.message || '操作失败', 'error');
  });
};

window.loadSystemSettings();
