window.colorRanges = [];

window.loadWorkSearchSettings = function() {
  api('/admin/work-search-settings').then(function(res) {
    if (res.error) { toast(res.error, 'error'); return; }
    window.colorRanges = (res.color_ranges || []).map(function(r) {
      return { value: r.value || '', label: r.label || '', names: (r.names || []).join(', '), description: r.description || '' };
    });
    if (window.colorRanges.length === 0) {
      window.colorRanges.push({ value: '', label: '', names: '', description: '' });
    }
    window.renderColorRanges();
  }).catch(function(err) {
    toast('加载颜色配置失败: ' + (err.message || err), 'error');
  });
};

window.renderColorRanges = function() {
  var tbody = document.getElementById('colorTableBody');
  var html = '';
  window.colorRanges.forEach(function(r, idx) {
    html += '<tr>' +
      '<td><input type="text" class="color-val" value="' + escAttr(r.value) + '" data-idx="' + idx + '" placeholder="如 red" /></td>' +
      '<td><input type="text" class="color-label" value="' + escAttr(r.label) + '" data-idx="' + idx + '" placeholder="如 红色" /></td>' +
      '<td><textarea class="color-names" data-idx="' + idx + '" rows="1" placeholder="红, 朱红, 绯红">' + esc(r.names) + '</textarea></td>' +
      '<td><textarea class="color-desc" data-idx="' + idx + '" rows="1">' + esc(r.description) + '</textarea></td>' +
      '<td><button onclick="window.removeColorRangeRow(' + idx + ')" class="btn btn-danger btn-sm">删除</button></td>' +
      '</tr>';
  });
  tbody.innerHTML = html;
  window.syncWorkSearchForm();
};

window.syncWorkSearchForm = function() {
  var valEls = document.querySelectorAll('.color-val');
  var labelEls = document.querySelectorAll('.color-label');
  var namesEls = document.querySelectorAll('.color-names');
  var descEls = document.querySelectorAll('.color-desc');
  window.colorRanges = [];
  for (var i = 0; i < valEls.length; i++) {
    window.colorRanges.push({
      value: valEls[i].value.trim(),
      label: labelEls[i].value.trim(),
      names: namesEls[i].value.trim(),
      description: descEls[i].value.trim()
    });
  }
};

window.addColorRangeRow = function() {
  window.syncWorkSearchForm();
  window.colorRanges.push({ value: '', label: '', names: '', description: '' });
  window.renderColorRanges();
};

window.removeColorRangeRow = function(idx) {
  window.syncWorkSearchForm();
  if (window.colorRanges.length <= 1) { toast('至少保留一个颜色范围', 'error'); return; }
  window.colorRanges.splice(idx, 1);
  window.renderColorRanges();
};

window.saveColorSettings = function() {
  window.syncWorkSearchForm();
  var seen = {};
  var valid = true;
  for (var i = 0; i < window.colorRanges.length; i++) {
    var r = window.colorRanges[i];
    if (!r.value || !r.label) { toast('第 ' + (i + 1) + ' 行的编码和名称不能为空', 'error'); valid = false; break; }
    if (seen[r.value]) { toast('编码重复: ' + r.value, 'error'); valid = false; break; }
    var namesList = r.names ? r.names.split(',').map(function(n) { return n.trim(); }).filter(function(n) { return n; }) : [];
    if (namesList.length === 0) { toast(r.label + ' 至少要包含一个颜色名', 'error'); valid = false; break; }
    seen[r.value] = true;
  }
  if (!valid) return;
  api('/admin/work-search-settings').then(function(current) {
    var tempRanges = current.temperature_ranges || [];
    var colorData = window.colorRanges.map(function(r) {
      var namesList = r.names ? r.names.split(',').map(function(n) { return n.trim(); }).filter(function(n) { return n; }) : [];
      return { value: r.value, label: r.label, names: namesList, description: r.description };
    });
    return api('/admin/work-search-settings', { method: 'PUT', body: JSON.stringify({ temperature_ranges: tempRanges, color_ranges: colorData }) });
  }).then(function() { toast('颜色配置保存成功'); }).catch(function(err) { toast('保存失败: ' + (err.message || err), 'error'); });
};

document.addEventListener('input', function(e) {
  if (e.target.closest('.color-config-page')) { window.syncWorkSearchForm(); }
});

window.loadWorkSearchSettings();
