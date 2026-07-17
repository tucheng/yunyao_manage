window.OXIDE_NAMES = [
  ['SiO2','sio2'],['Al2O3','al2o3'],['Fe2O3','fe2o3'],['TiO2','tio2'],
  ['CaO','cao'],['MgO','mgo'],['Na2O','na2o'],['K2O','k2o'],
  ['ZnO','zno'],['B2O3','b2o3'],['P2O5','p2o5'],['Li2O','li2o'],
  ['MnO2','mno2'],['CoO','coo'],['SnO2','sno2'],['CuO','cuo'],
  ['Cr2O3','cr2o3'],['PbO','pbo'],['BaO','bao'],['SrO','sro'],['LOI','loi']
];

window.materialPage = 1;
window.lastMaterialData = [];

window.loadMaterials = function() {
  var search = document.getElementById('materialSearch').value.trim();
  var url = '/admin/materials?page=' + window.materialPage + '&page_size=30';
  if (search) url += '&search=' + encodeURIComponent(search);
  var status = document.getElementById('materialStatus').value;
  if (status) url += '&status=' + encodeURIComponent(status);
  if (document.getElementById('duplicateOnly').checked) url += '&duplicate_only=true';

  api(url).then(function(data) {
    var list = data.data || [];
    window.lastMaterialData = list;
    var total = data.total || list.length;
    var totalPages = Math.ceil(total / 30) || 1;

    var tbody = document.getElementById('materialTableBody');
    if (list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#999;padding:30px">暂无材料数据</td></tr>';
    } else {
      tbody.innerHTML = list.map(function(m) {
        var srcLabel = m.source === 'local' ? '国产' : '海外';
        var statusLabel = { initial: '初始', submitted: '待审核', recalculated: '已重新计算' }[m.status] || m.status || '-';
        var statusClass = m.status === 'submitted' ? 'badge-overseas' : 'badge-neutral';
        return '<tr>' +
          '<td>' + m.id + '</td>' +
          '<td><strong>' + esc(m.name) + '</strong>' + (m.variant_name ? '<br><small style="color:#8B6914">' + esc(m.variant_name) + '</small>' : '') + (m.name_en ? '<br><small style="color:#999">' + esc(m.name_en) + '</small>' : '') + '</td>' +
          '<td><span class="badge ' + statusClass + '">' + statusLabel + '</span>' + (m.is_default ? '<br><small style="color:#287a3d">默认变体</small>' : '') + '</td>' +
          '<td><button class="btn btn-sm" onclick="window.showMaterialFamily(' + m.family_id + ')">' + Number(m.variant_count || 1) + ' 个</button></td>' +
          '<td><button class="btn btn-sm" onclick="window.showAffectedRecipes(' + m.id + ')">' + Number(m.affected_recipe_count || 0) + '</button></td>' +
          '<td><span class="badge ' + (m.source === 'local' ? 'badge-neutral' : 'badge-overseas') + '">' + srcLabel + '</span></td>' +
          '<td><button class="btn btn-sm" onclick="window.showSubstitutions(' + m.id + ')">相似品</button> ' +
          '<button class="btn btn-sm btn-primary" onclick="window.showMaterialDetail(' + m.id + ')" style="margin-left:4px">详情</button> ' +
          '<button class="btn btn-sm" onclick="window.editMaterial(' + m.id + ')">编辑</button> ' +
          (m.status === 'submitted' ? '<button class="btn btn-sm btn-primary" onclick="window.approveMaterial(' + m.id + ')">审核重算</button> <button class="btn btn-sm" onclick="window.rejectMaterial(' + m.id + ')">退回</button> ' : '') +
          (m.is_default ? '' : '<button class="btn btn-sm" onclick="window.setDefaultMaterial(' + m.id + ')">设默认</button> ') +
          '<button class="btn btn-sm btn-danger" onclick="window.deleteMaterial(' + m.id + ')" style="margin-left:4px">删除</button></td>' +
          '</tr>';
      }).join('');
    }

    var pag = document.getElementById('materialPagination');
    pag.innerHTML =
      '<button class="btn btn-sm" onclick="window.materialPage--;window.loadMaterials()" ' + (window.materialPage <= 1 ? 'disabled' : '') + '>‹</button>' +
      '<span>第 ' + data.page + ' / ' + totalPages + ' 页</span>' +
      '<button class="btn btn-sm" onclick="window.materialPage++;window.loadMaterials()" ' + (window.materialPage >= totalPages ? 'disabled' : '') + '>›</button>';
  }).catch(function(e) { toast('加载失败: ' + (e.message || e), 'error'); });
};

window.deleteMaterial = function(id) {
  var material = window.lastMaterialData.find(function(x) { return x.id === id; });
  var name = material ? material.name : ('ID ' + id);
  if (!confirm('确定删除材料“' + name + '”，此操作无法撤销！')) return;

  api('/admin/materials/' + id, { method: 'DELETE' }).then(function() {
    toast('材料已删除');
    if (window.lastMaterialData.length === 1 && window.materialPage > 1) {
      window.materialPage--;
    }
    window.loadMaterials();
  }).catch(function(e) {
    toast(e.message || '删除失败', 'error');
  });
};

window.showSubstitutions = function(materialId) {
  var src = window.lastMaterialData.find(function(x) { return x.id === materialId; });
  if (!src) { toast('未找到原材料数据', 'error'); return; }
  api('/materials/' + materialId + '/substitutions').then(function(subs) {
    if (!subs.length) { toast('暂无相似品数据', 'error'); return; }
    var oxides = window.OXIDE_NAMES.filter(function(o) { return src[o[1]] != null || subs.some(function(s) { return s[o[1]] != null; }); });
    var oxideLabels = oxides.map(function(o) { return o[0]; });
    var oxideKeys = oxides.map(function(o) { return o[1]; });

    var html = '<div style="max-height:70vh;overflow:auto"><table style="font-size:12px;white-space:nowrap"><thead><tr>' +
      '<th style="position:sticky;top:0;background:#fafafa;z-index:1">材料 / 成分</th>' +
      oxideLabels.map(function(l) { return '<th style="position:sticky;top:0;background:#fafafa;z-index:1">' + l + '</th>'; }).join('') +
      '<th style="position:sticky;top:0;background:#fafafa;z-index:1">相似度</th>' +
      '</tr></thead><tbody>';

    html += '<tr style="background:#fff8e1"><td style="font-weight:600;color:#8B6914"><strong>' + esc(src.name) + '</strong><br><small>原料</small></td>';
    oxideKeys.forEach(function(k) { html += '<td style="text-align:center;font-weight:600">' + (src[k] != null ? src[k] : '-') + '</td>'; });
    html += '<td style="text-align:center;color:#999">-</td></tr>';

    subs.forEach(function(s) {
      html += '<tr><td style="font-weight:600">' + esc(s.target_name) + '</td>';
      oxideKeys.forEach(function(k) {
        var tVal = s[k];
        var srcVal = src[k];
        var diff = (srcVal != null && tVal != null) ? (tVal - srcVal).toFixed(2) : null;
        var cell = tVal != null ? tVal : '-';
        if (diff != null && Math.abs(diff) > 0.5) { cell += ' <span style="color:' + (diff > 0 ? '#e74c3c' : '#27ae60') + ';font-weight:600">(' + (diff > 0 ? '+' : '') + diff + ')</span>'; }
        html += '<td style="text-align:center">' + cell + '</td>';
      });
      html += '<td style="text-align:center">' + Number(s.similarity_score || 0).toFixed(2) + '%</td></tr>';
    });
    html += '</tbody></table></div>';
    window.showModal(html);
  }).catch(function(e) { toast(e.message || '加载失败', 'error'); });
};

window.showMaterialDetail = function(id) {
  var m = window.lastMaterialData.find(function(x) { return x.id === id; });
  if (!m) { toast('未找到材料', 'error'); return; }
  var oxides = window.OXIDE_NAMES.map(function(o) { return [o[0], m[o[1]]]; }).filter(function(x) { return x[1] != null; });
  var thermal = m.thermal_expansion != null ? '<tr><td>热膨胀</td><td>' + m.thermal_expansion + '</td></tr>' : '';
  var formula = m.formula ? '<tr><td>分子式</td><td>' + esc(m.formula) + '</td></tr>' : '';
  var mw = m.molecular_weight ? '<tr><td>分子量</td><td>' + esc(m.molecular_weight) + '</td></tr>' : '';
  var cat = m.category ? '<tr><td>分类</td><td>' + esc(m.category) + '</td></tr>' : '';
  var html = '<div style="min-width:320px"><h3 style="margin-bottom:8px">' + esc(m.name) + '</h3>' +
    '<p style="font-size:13px;color:#888;margin-bottom:12px">' + (m.name_en ? esc(m.name_en) : '') + ' · ' + (m.source === 'local' ? '国产' : '海外') + '</p>' +
    '<table style="font-size:13px"><thead><tr><th style="width:80px">成分</th><th>含量%</th></tr></thead><tbody>' +
    formula + mw + cat +
    oxides.map(function(o) { return '<tr><td>' + o[0] + '</td><td>' + o[1] + '</td></tr>'; }).join('') +
    thermal + '</tbody></table></div>';
  window.showModal(html);
};

window.editMaterial = function(id) {
  var m = window.lastMaterialData.find(function(x) { return x.id === id; });
  if (!m) { toast('未找到材料', 'error'); return; }
  var editable = { name: m.name, name_en: m.name_en || '', variant_name: m.variant_name || '', formula: m.formula || '', molecular_weight: m.molecular_weight || '', category: m.category || '' };
  window.OXIDE_NAMES.forEach(function(o) { editable[o[1]] = m[o[1]]; });
  editable.thermal_expansion = m.thermal_expansion;
  var raw = prompt('编辑材料 JSON（空值用 null）', JSON.stringify(editable, null, 2));
  if (raw === null) return;
  var payload;
  try { payload = JSON.parse(raw); } catch (e) { toast('JSON 格式错误', 'error'); return; }
  api('/admin/materials/' + id, { method: 'PUT', body: JSON.stringify(payload) }).then(function() {
    toast('材料已更新'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '更新失败', 'error'); });
};

window.scanMaterialDuplicates = function() {
  api('/admin/material-dedup/groups').then(function(data) {
    var rows = (data.groups || []).map(function(g) {
      return '<tr><td>' + g.family_id + '</td><td><button class="btn btn-sm" onclick="window.showMaterialFamily(' + g.family_id + ')">' + esc(g.name) + '</button></td><td>' + g.variant_count + '</td><td>' + (g.duplicate_type === 'exact' ? '完全重复' : '成分冲突') + '</td><td>' + g.affected_recipe_count + '</td></tr>';
    }).join('');
    window.showModal('<h3>重复材料扫描</h3><p>共 ' + data.total + ' 组；完全重复 ' + data.exact + ' 组；成分冲突 ' + data.conflict + ' 组。</p><div style="max-height:65vh;overflow:auto"><table><thead><tr><th>ID</th><th>材料族</th><th>变体</th><th>类型</th><th>影响配方</th></tr></thead><tbody>' + rows + '</tbody></table></div>');
  }).catch(function(e) { toast(e.message || '扫描失败', 'error'); });
};

window.backfillMaterialLinks = function() {
  if (!confirm('将按材料族默认变体关联历史配料。成分冲突且未设置默认的材料不会自动关联。确认继续？')) return;
  api('/admin/material-dedup/backfill-links', { method: 'POST' }).then(function(data) {
    toast(data.message || '关联完成'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '关联失败', 'error'); });
};

window.showMaterialFamily = function(familyId) {
  if (!familyId) { toast('该材料尚未归入材料族', 'error'); return; }
  api('/admin/material-families/' + familyId).then(function(data) {
    var keys = window.OXIDE_NAMES.map(function(o) { return o[1]; });
    var rows = (data.variants || []).map(function(m) {
      var summary = keys.filter(function(k) { return m[k] != null; }).slice(0, 6).map(function(k) { return k.toUpperCase() + '=' + m[k]; }).join('，');
      return '<tr><td>' + m.id + (m.is_default ? ' <span style="color:#287a3d">默认</span>' : '') + '</td><td>' + esc(m.variant_name || m.name_en || '-') + '</td><td>' + esc(summary || '无成分') + '</td><td>' + m.status + '</td><td>' + m.affected_recipe_count + '</td><td>' +
        (m.is_default ? '' : '<button class="btn btn-sm" onclick="window.setDefaultMaterial(' + m.id + ')">设默认</button> ') +
        '<button class="btn btn-sm" onclick="window.promptMergeMaterial(' + m.id + ',' + data.default_material_id + ')">合并</button></td></tr>';
    }).join('');
    window.showModal('<h3>' + esc(data.name) + ' · 材料族对比</h3><div style="max-height:70vh;overflow:auto"><table><thead><tr><th>ID</th><th>变体</th><th>主要成分</th><th>状态</th><th>配方</th><th>操作</th></tr></thead><tbody>' + rows + '</tbody></table></div>');
  }).catch(function(e) { toast(e.message || '加载材料族失败', 'error'); });
};

window.setDefaultMaterial = function(id) {
  api('/admin/materials/' + id + '/set-default', { method: 'POST' }).then(function() {
    toast('已设为默认变体'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '设置失败', 'error'); });
};

window.promptMergeMaterial = function(sourceId, suggestedTargetId) {
  var targetId = prompt('请输入要合并到的目标材料 ID', suggestedTargetId || '');
  if (!targetId) return;
  if (!confirm('将材料 ' + sourceId + ' 软合并到 ' + targetId + '，关联配方和相似关系也会迁移。确认继续？')) return;
  api('/admin/materials/' + sourceId + '/merge', { method: 'POST', body: JSON.stringify({ target_material_id: Number(targetId), reason: '管理员在材料族对比中合并' }) }).then(function() {
    toast('合并完成'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '合并失败', 'error'); });
};

window.autoMergeExactMaterials = function() {
  if (!confirm('只会合并成分指纹完全一致的记录，并保留审计快照。确认执行？')) return;
  api('/admin/material-dedup/auto-merge-exact', { method: 'POST' }).then(function(data) {
    toast(data.message || '处理完成'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '自动合并失败', 'error'); });
};

window.showAffectedRecipes = function(id) {
  api('/admin/materials/' + id + '/affected-recipes').then(function(rows) {
    var html = rows.length ? rows.map(function(r) { return '<tr><td>' + r.id + '</td><td>' + esc(r.recipe_no || '-') + '</td><td>' + esc(r.title) + '</td><td>' + r.user_id + '</td></tr>'; }).join('') : '<tr><td colspan="4">暂无关联配方</td></tr>';
    window.showModal('<h3>影响的配方</h3><table><thead><tr><th>ID</th><th>编号</th><th>名称</th><th>用户</th></tr></thead><tbody>' + html + '</tbody></table>');
  }).catch(function(e) { toast(e.message || '加载失败', 'error'); });
};

window.approveMaterial = function(id) {
  if (!confirm('审核通过后将使用新成分重新计算所有受影响配方。确认继续？')) return;
  api('/admin/materials/' + id + '/approve-and-recalculate', { method: 'POST', body: '{}' }).then(function(data) {
    toast(data.message || '审核完成'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '审核失败', 'error'); });
};

window.rejectMaterial = function(id) {
  var reason = prompt('请输入退回原因', '请完善材料分子数据');
  if (reason === null) return;
  api('/admin/materials/' + id + '/reject', { method: 'POST', body: JSON.stringify({ reason: reason }) }).then(function() {
    toast('已退回'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '退回失败', 'error'); });
};

window.showMaterialMergeLogs = function() {
  api('/admin/material-merge-logs').then(function(rows) {
    var html = rows.map(function(r) { return '<tr><td>' + r.id + '</td><td>' + r.source_material_id + ' → ' + r.target_material_id + '</td><td>' + esc(r.reason || '-') + '</td><td>' + esc(r.merged_at || '-') + '</td><td>' + (r.rolled_back_at ? '已回滚' : '<button class="btn btn-sm" onclick="window.rollbackMaterialMerge(' + r.id + ')">回滚</button>') + '</td></tr>'; }).join('');
    window.showModal('<h3>材料合并记录</h3><div style="max-height:65vh;overflow:auto"><table><thead><tr><th>ID</th><th>合并</th><th>原因</th><th>时间</th><th>操作</th></tr></thead><tbody>' + html + '</tbody></table></div>');
  }).catch(function(e) { toast(e.message || '加载失败', 'error'); });
};

window.rollbackMaterialMerge = function(id) {
  if (!confirm('确认回滚这次材料合并？配料关联、别名和相似关系将尽量恢复到合并前状态。')) return;
  api('/admin/material-merge-logs/' + id + '/rollback', { method: 'POST' }).then(function(data) {
    toast(data.message || '回滚完成'); window.loadMaterials();
  }).catch(function(e) { toast(e.message || '回滚失败', 'error'); });
};

window.loadMaterials();
