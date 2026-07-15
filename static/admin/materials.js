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

  api(url).then(function(data) {
    var list = data.data || [];
    window.lastMaterialData = list;
    var total = data.total || list.length;
    var totalPages = Math.ceil(total / 30) || 1;

    var tbody = document.getElementById('materialTableBody');
    if (list.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#999;padding:30px">暂无材料数据</td></tr>';
    } else {
      tbody.innerHTML = list.map(function(m) {
        var srcLabel = m.source === 'local' ? '国产' : '海外';
        return '<tr>' +
          '<td>' + m.id + '</td>' +
          '<td><strong>' + esc(m.name) + '</strong>' + (m.name_en ? '<br><small style="color:#999">' + esc(m.name_en) + '</small>' : '') + '</td>' +
          '<td style="font-size:12px;color:#666;max-width:160px;overflow:hidden;text-overflow:ellipsis">' + esc(m.formula || '-') + '</td>' +
          '<td><span class="badge ' + (m.source === 'local' ? 'badge-neutral' : 'badge-overseas') + '">' + srcLabel + '</span></td>' +
          '<td><button class="btn btn-sm" onclick="window.showSubstitutions(' + m.id + ')">相似品</button> ' +
          '<button class="btn btn-sm btn-primary" onclick="window.showMaterialDetail(' + m.id + ')" style="margin-left:4px">详情</button> ' +
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

window.loadMaterials();
