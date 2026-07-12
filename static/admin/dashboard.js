window.loadStats = function() {
  api('/admin/stats').then(function(res) {
    var html = '';
    var items = [
      { key: 'user_count', label: '总用户' },
      { key: 'recipe_count', label: '配方总数' },
      { key: 'paid_recipe_count', label: '付费配方' },
      { key: 'work_count', label: '作品总数' },
      { key: 'muted_count', label: '已禁言' }
    ];
    items.forEach(function(item) {
      var val = res[item.key];
      if (val === undefined || val === null) val = 0;
      html += '<div class="stat-card"><div class="num">' + val + '</div><div class="label">' + item.label + '</div></div>';
    });
    document.getElementById('statsContainer').innerHTML = html;
  }).catch(function(err) {
    toast('获取统计数据失败: ' + (err.message || err), 'error');
  });
};
window.loadStats();
