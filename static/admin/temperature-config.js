window.temperatureRanges = [];

window.loadWorkSearchSettings = function() {
  api('/admin/work-search-settings').then(function(res) {
    if (res.error) { toast(res.error, 'error'); return; }
    window.temperatureRanges = (res.temperature_ranges || []).map(function(r) {
      return { value: r.value || '', label: r.label || '', min: r.min != null ? r.min : 0, max: r.max != null ? r.max : 0, description: r.description || '' };
    });
    if (window.temperatureRanges.length === 0) {
      window.temperatureRanges.push({ value: '', label: '', min: 0, max: 0, description: '' });
    }
    window.renderTemperatureRanges();
  }).catch(function(err) {
    toast('加载温度配置失败: ' + (err.message || err), 'error');
  });
};

window.renderTemperatureRanges = function() {
  var tbody = document.getElementById('temperatureTableBody');
  var html = '';
  window.temperatureRanges.forEach(function(r, idx) {
    html += '<tr>' +
      '<td><input type="text" class="temp-val" value="' + escAttr(r.value) + '" data-idx="' + idx + '" placeholder="如 low" /></td>' +
      '<td><input type="text" class="temp-label" value="' + escAttr(r.label) + '" data-idx="' + idx + '" placeholder="如 低温" /></td>' +
      '<td><input type="number" class="temp-min narrow" value="' + escAttr(r.min) + '" data-idx="' + idx + '" step="0.1" /></td>' +
      '<td><input type="number" class="temp-max narrow" value="' + escAttr(r.max) + '" data-idx="' + idx + '" step="0.1" /></td>' +
      '<td><textarea class="temp-desc" data-idx="' + idx + '" rows="1">' + esc(r.description) + '</textarea></td>' +
      '<td><button onclick="window.removeTemperatureRow(' + idx + ')" class="btn btn-danger btn-sm">删除</button></td>' +
      '</tr>';
  });
  tbody.innerHTML = html;
  window.syncWorkSearchForm();
};

window.syncWorkSearchForm = function() {
  var valEls = document.querySelectorAll('.temp-val');
  var labelEls = document.querySelectorAll('.temp-label');
  var minEls = document.querySelectorAll('.temp-min');
  var maxEls = document.querySelectorAll('.temp-max');
  var descEls = document.querySelectorAll('.temp-desc');
  window.temperatureRanges = [];
  for (var i = 0; i < valEls.length; i++) {
    window.temperatureRanges.push({
      value: valEls[i].value.trim(),
      label: labelEls[i].value.trim(),
      min: parseFloat(minEls[i].value) || 0,
      max: parseFloat(maxEls[i].value) || 0,
      description: descEls[i].value.trim()
    });
  }
};

window.addTemperatureRow = function() {
  window.syncWorkSearchForm();
  window.temperatureRanges.push({ value: '', label: '', min: 0, max: 0, description: '' });
  window.renderTemperatureRanges();
};

window.removeTemperatureRow = function(idx) {
  window.syncWorkSearchForm();
  if (window.temperatureRanges.length <= 1) { toast('至少保留一个温度范围', 'error'); return; }
  window.temperatureRanges.splice(idx, 1);
  window.renderTemperatureRanges();
};

window.saveTemperatureSettings = function() {
  window.syncWorkSearchForm();
  var seen = {};
  var valid = true;
  for (var i = 0; i < window.temperatureRanges.length; i++) {
    var r = window.temperatureRanges[i];
    if (!r.value || !r.label) { toast('第 ' + (i + 1) + ' 行的编码和名称不能为空', 'error'); valid = false; break; }
    if (seen[r.value]) { toast('编码重复: ' + r.value, 'error'); valid = false; break; }
    if (r.min > r.max) { toast(r.label + ' 的最低温不能大于最高温', 'error'); valid = false; break; }
    seen[r.value] = true;
  }
  if (!valid) return;
  api('/admin/work-search-settings').then(function(current) {
    var colorRanges = current.color_ranges || [];
    return api('/admin/work-search-settings', { method: 'PUT', body: JSON.stringify({ temperature_ranges: window.temperatureRanges, color_ranges: colorRanges }) });
  }).then(function() { toast('温度配置保存成功'); }).catch(function(err) { toast('保存失败: ' + (err.message || err), 'error'); });
};

document.addEventListener('input', function(e) {
  if (e.target.closest('.temperature-config-page')) { window.syncWorkSearchForm(); }
});

window.loadWorkSearchSettings();
