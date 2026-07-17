window.OXIDE_NAMES = [
  ['SiO2','sio2'],['Al2O3','al2o3'],['Fe2O3','fe2o3'],['TiO2','tio2'],
  ['CaO','cao'],['MgO','mgo'],['Na2O','na2o'],['K2O','k2o'],
  ['ZnO','zno'],['B2O3','b2o3'],['P2O5','p2o5'],['Li2O','li2o'],
  ['MnO2','mno2'],['CoO','coo'],['SnO2','sno2'],['CuO','cuo'],
  ['Cr2O3','cr2o3'],['PbO','pbo'],['BaO','bao'],['SrO','sro'],['LOI','loi']
];

window.materialPage = 1;
window.lastMaterialData = [];

window.materialStatusText = function(status, affectedCount) {
  return { initial: '初始', modified: '已修改', submitted: '已提交', recalculated: '已审核' }[status] || status || '初始';
};

window.loadMaterials = function() {
  var search = document.getElementById('materialSearch').value.trim();
  var status = document.getElementById('materialStatus').value;
  var url = '/admin/materials?page=' + window.materialPage + '&page_size=30';
  if (search) url += '&search=' + encodeURIComponent(search);
  if (status) url += '&status=' + encodeURIComponent(status);
  api(url).then(function(data) {
    var list = data.data || [];
    window.lastMaterialData = list;
    var tbody = document.getElementById('materialTableBody');
    tbody.innerHTML = list.length ? list.map(function(m) {
      var owner = m.owner ? esc(m.owner.name || ('用户 ' + m.owner.id)) : '-';
      var statusClass = m.status === 'submitted' ? 'badge-danger' : (m.status === 'recalculated' ? 'badge-reviewed' : 'badge-neutral');
      return '<tr>' +
        '<td>' + m.id + '</td>' +
        '<td><strong>' + esc(m.name || '-') + '</strong><br><small>' + esc(m.name_en || '-') + '</small></td>' +
        '<td><span class="badge ' + statusClass + '">' + window.materialStatusText(m.status, m.affected_recipe_count || 0) + '</span></td>' +
        '<td><button class="btn btn-sm" onclick="window.showMaterialAffectedRecipes(' + m.id + ')">' + (m.affected_recipe_count || 0) + '</button></td>' +
        '<td>' + owner + '</td>' +
        '<td>' +
          '<button class="btn btn-sm" onclick="window.editMaterial(' + m.id + ')">编辑</button> ' +
          ((m.status === 'modified' || m.status === 'recalculated' || (m.affected_recipe_count || 0) > 0) ? '<button class="btn btn-sm btn-primary" onclick="window.recalculateMaterial(' + m.id + ')">重新算 Seger</button> ' : '') +
          ((m.affected_recipe_count || 0) === 0 && m.status === 'submitted' ? '<button class="btn btn-sm btn-primary" onclick="window.reviewMaterial(' + m.id + ')">审核</button> ' : '') +
          '<button class="btn btn-sm btn-danger" onclick="window.deleteMaterial(' + m.id + ',' + (m.affected_recipe_count || 0) + ')">删除</button>' +
        '</td></tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;color:#999;padding:30px">暂无材料数据</td></tr>';

    var totalPages = Math.ceil((data.total || 0) / (data.page_size || 30)) || 1;
    document.getElementById('materialPagination').innerHTML =
      '<button class="btn btn-sm" onclick="window.materialPage--;window.loadMaterials()" ' + (window.materialPage <= 1 ? 'disabled' : '') + '>上一页</button>' +
      '<span>第 ' + window.materialPage + ' / ' + totalPages + ' 页</span>' +
      '<button class="btn btn-sm" onclick="window.materialPage++;window.loadMaterials()" ' + (window.materialPage >= totalPages ? 'disabled' : '') + '>下一页</button>';
  }).catch(function(e) { toast(e.message || '材料加载失败', 'error'); });
};

window.showMaterialAffectedRecipes = function(id) {
  api('/admin/materials/' + id + '/affected-recipes').then(function(rows) {
    var html = rows.length ? rows.map(function(r) {
      return '<tr><td>' + r.id + '</td><td>' + esc(r.recipe_no || '-') + '</td><td>' + esc(r.title || '-') + '</td><td>' + r.user_id + '</td></tr>';
    }).join('') : '<tr><td colspan="4">暂无关联配方</td></tr>';
    window.showModal('<h3>影响的配方</h3><table><thead><tr><th>ID</th><th>编号</th><th>名称</th><th>用户</th></tr></thead><tbody>' + html + '</tbody></table>');
  }).catch(function(e) { toast(e.message || '加载失败', 'error'); });
};

window.editMaterial = function(id) {
  var m = window.lastMaterialData.find(function(item) { return item.id === id; });
  if (!m) return;
  var oxideInputs = window.OXIDE_NAMES.map(function(pair) {
    return '<div class="form-group" style="min-width:120px"><label>' + pair[0] + '</label><input id="mat_' + pair[1] + '" type="number" step="any" value="' + (m[pair[1]] == null ? '' : m[pair[1]]) + '"></div>';
  }).join('');
  window.showModal('<h3>编辑材料 #' + id + '</h3>' +
    '<div class="form-group"><label>中文名</label><input id="mat_name" value="' + esc(m.name || '') + '"></div>' +
    '<div class="form-group"><label>英文名</label><input id="mat_name_en" value="' + esc(m.name_en || '') + '"></div>' +
    '<div class="form-group"><label>分子式</label><input id="mat_formula" value="' + esc(m.formula || '') + '"></div>' +
    '<div style="display:flex;flex-wrap:wrap;gap:8px">' + oxideInputs + '</div>' +
    '<button class="btn btn-primary" onclick="window.saveMaterial(' + id + ')">保存</button>');
};

window.saveMaterial = function(id) {
  var body = {
    name: document.getElementById('mat_name').value.trim(),
    name_en: document.getElementById('mat_name_en').value.trim(),
    formula: document.getElementById('mat_formula').value.trim()
  };
  window.OXIDE_NAMES.forEach(function(pair) {
    var raw = document.getElementById('mat_' + pair[1]).value.trim();
    body[pair[1]] = raw === '' ? null : Number(raw);
  });
  api('/admin/materials/' + id, { method: 'PUT', body: JSON.stringify(body) }).then(function() {
    toast('材料已保存，状态已更新为已修改');
    closeModal('subModal');
    window.loadMaterials();
  }).catch(function(e) { toast(e.message || '保存失败', 'error'); });
};

window.recalculateMaterial = function(id) {
  if (!confirm('审核该材料并重新计算所有受影响配方的 Seger 数据？')) return;
  api('/admin/materials/' + id + '/recalculate', { method: 'POST', body: JSON.stringify({}) }).then(function(data) {
    var r = data.result || {};
    toast('重算完成：成功 ' + (r.succeeded || 0) + '，失败 ' + (r.failed || 0));
    window.loadMaterials();
  }).catch(function(e) { toast(e.message || '重算失败', 'error'); });
};

window.reviewMaterial = function(id) {
  if (!confirm('该材料暂无关联配方，确认审核通过并允许其参与后续釉料分析？')) return;
  api('/admin/materials/' + id + '/recalculate', { method: 'POST', body: JSON.stringify({}) }).then(function() {
    toast('材料已审核');
    window.loadMaterials();
  }).catch(function(e) { toast(e.message || '审核失败', 'error'); });
};

window.deleteMaterial = function(id, affectedCount) {
  if (affectedCount > 0) {
    toast('该材料影响 ' + affectedCount + ' 个配方，不能删除', 'error');
    return;
  }
  if (!confirm('确定删除材料 #' + id + '？此操作不可恢复。')) return;
  api('/admin/materials/' + id, { method: 'DELETE' }).then(function() {
    toast('材料已删除');
    window.loadMaterials();
  }).catch(function(e) { toast(e.message || '删除失败', 'error'); });
};

window.showMaterialRecalculationLogs = function() {
  api('/admin/material-recalculation-logs').then(function(rows) {
    var html = rows.length ? rows.map(function(r) {
      return '<tr><td>' + r.id + '</td><td>' + r.material_id + '</td><td>' + r.affected_recipe_count + '</td><td>' + r.success_count + '</td><td>' + r.failed_count + '</td><td>' + esc(r.created_at || '-') + '</td></tr>';
    }).join('') : '<tr><td colspan="6">暂无重算记录</td></tr>';
    window.showModal('<h3>Seger 重算日志</h3><table><thead><tr><th>ID</th><th>材料</th><th>影响配方</th><th>成功</th><th>失败</th><th>时间</th></tr></thead><tbody>' + html + '</tbody></table>');
  }).catch(function(e) { toast(e.message || '日志加载失败', 'error'); });
};

window.loadMaterials();
