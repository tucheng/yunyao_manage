window.editingLevelId = null;

window.loadLevels = function() {
  api('/admin/levels').then(function(levels) {
    var tbody = document.getElementById('levelTableBody');
    tbody.innerHTML = levels.map(function(l) {
      return '<tr>' +
        '<td>' + l.id + '</td>' +
        '<td><strong>' + esc(l.name) + '</strong></td>' +
        '<td>' + l.max_recipes + '</td>' +
        '<td>' + l.max_works + '</td>' +
        '<td>' + (l.max_views || '不限') + '</td>' +
        '<td>' + l.user_count + '</td>' +
        '<td><button class="btn btn-sm" onclick="window.showLevelModal(' + l.id + ')">编辑</button></td>' +
        '</tr>';
    }).join('');
  });
};

window.showLevelModal = function(id) {
  window.editingLevelId = id || null;
  document.getElementById('levelModalTitle').textContent = id ? '编辑等级' : '新建等级';
  document.getElementById('levelDeleteBtn').style.display = (id && id <= 3) ? 'none' : 'inline-flex';
  document.getElementById('levelEditName').disabled = !!(id && id <= 3);
  if (id) {
    api('/admin/levels').then(function(levels) {
      var l = levels.find(function(x) { return x.id === id; });
      if (!l) return;
      document.getElementById('levelEditName').value = l.name;
      document.getElementById('levelEditMaxRecipes').value = l.max_recipes;
      document.getElementById('levelEditMaxWorks').value = l.max_works;
      document.getElementById('levelEditMaxViews').value = l.max_views;
      document.getElementById('levelEditSort').value = l.sort_order;
      document.getElementById('levelEditDesc').value = l.description;
    });
  } else {
    document.getElementById('levelEditName').value = '';
    document.getElementById('levelEditMaxRecipes').value = 10;
    document.getElementById('levelEditMaxWorks').value = 50;
    document.getElementById('levelEditMaxViews').value = 0;
    document.getElementById('levelEditSort').value = 99;
    document.getElementById('levelEditDesc').value = '';
  }
  window.openModal('levelModal');
};

window.saveLevel = function() {
  var data = {
    name: document.getElementById('levelEditName').value,
    max_recipes: parseInt(document.getElementById('levelEditMaxRecipes').value) || 0,
    max_works: parseInt(document.getElementById('levelEditMaxWorks').value) || 0,
    max_views: parseInt(document.getElementById('levelEditMaxViews').value) || 0,
    sort_order: parseInt(document.getElementById('levelEditSort').value) || 0,
    description: document.getElementById('levelEditDesc').value
  };
  if (!data.name) { toast('请输入等级名称', 'error'); return; }
  var url = window.editingLevelId ? '/admin/levels/' + window.editingLevelId : '/admin/levels';
  var method = window.editingLevelId ? 'PUT' : 'POST';
  api(url, { method: method, body: JSON.stringify(data) }).then(function() {
    toast(window.editingLevelId ? '等级已更新' : '等级已创建');
    window.closeModal('levelModal');
    window.loadLevels();
  }).catch(function(e) {
    toast(e.message || '保存失败', 'error');
  });
};

window.deleteLevel = function() {
  if (!confirm('确定删除此等级？已有用户将被影响')) return;
  api('/admin/levels/' + window.editingLevelId, { method: 'DELETE' }).then(function() {
    toast('等级已删除');
    window.closeModal('levelModal');
    window.loadLevels();
  }).catch(function(e) {
    toast(e.message || '删除失败', 'error');
  });
};

window.loadLevels();
