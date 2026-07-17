window.ATTR_CATEGORIES = {
  type: '类型', body_material: '底坯', kiln_type: '烧制方式', atmosphere: '气氛', surface: '釉面质感', transparency: '透明度'
};
window.attrData = {};
window.activeAttrCategory = 'type';

window.loadWorkAttributes = function() {
  api('/admin/work-attributes').then(function(grouped) {
    window.attrData = grouped || {};
    var container = document.getElementById('attrPanels');
    var cats = Object.entries(window.ATTR_CATEGORIES);
    if (!window.ATTR_CATEGORIES[window.activeAttrCategory]) window.activeAttrCategory = cats[0][0];

    var tabsHtml = '';
    for (var ci = 0; ci < cats.length; ci++) {
      var cat = cats[ci][0], label = cats[ci][1];
      var count = (grouped[cat] || []).length;
      tabsHtml += '<button class="attr-tab ' + (cat === window.activeAttrCategory ? 'attr-tab-active' : '') +
        '" data-cat="' + cat + '" onclick="window.switchAttrTab(\'' + cat + '\')">' + esc(label) + ' (' + count + ')</button>';
    }
    document.getElementById('attrTabHeader').innerHTML = tabsHtml;

    var panelsHtml = '';
    for (var ci2 = 0; ci2 < cats.length; ci2++) {
      var c = cats[ci2][0], lbl = cats[ci2][1];
      var items = grouped[c] || [];
      panelsHtml += '<div class="attr-panel" data-cat="' + c + '" style="display:' + (c === window.activeAttrCategory ? 'block' : 'none') + '">' +
        '<div class="attr-batch-add">' +
        '<textarea id="attr-batch-' + c + '" rows="2" placeholder="每行一个选项，批量添加..."></textarea>' +
        '<button class="btn btn-sm btn-primary" onclick="window.batchAddAttr(\'' + c + '\')">+ 添加</button></div>' +
        '<div class="attr-list" id="attr-list-' + c + '">' +
        items.map(function(opt, idx) {
          return '<div class="attr-item" draggable="true" data-id="' + opt.id + '" data-cat="' + c + '" data-sort="' + opt.sort_order + '">' +
            '<span class="attr-drag-handle" draggable="true">⠿</span>' +
            '<input type="text" class="attr-item-input" value="' + escAttr(opt.value) + '" data-field="value">' +
            '<button class="btn btn-danger btn-sm" onclick="window.deleteAttrOption(this)">✕</button></div>';
        }).join('') +
        '</div></div>';
    }
    container.innerHTML = panelsHtml;
    window.setupDragAndDrop();
  }).catch(function(e) { toast(e.message || '加载失败', 'error'); });
};

window.switchAttrTab = function(cat) {
  window.activeAttrCategory = cat;
  document.querySelectorAll('.attr-tab').forEach(function(b) { b.classList.remove('attr-tab-active'); });
  document.querySelector('.attr-tab[data-cat="' + cat + '"]').classList.add('attr-tab-active');
  document.querySelectorAll('.attr-panel').forEach(function(p) { p.style.display = p.dataset.cat === cat ? 'block' : 'none'; });
};

window.batchAddAttr = function(cat) {
  var ta = document.getElementById('attr-batch-' + cat);
  var lines = ta.value.split('\n').map(function(s) { return s.trim(); }).filter(function(s) { return s; });
  if (!lines.length) { toast('请输入选项值', 'error'); return; }
  ta.value = '';
  var list = document.getElementById('attr-list-' + cat);
  for (var i = 0; i < lines.length; i++) {
    var div = document.createElement('div');
    div.className = 'attr-item';
    div.draggable = true;
    div.dataset.cat = cat;
    div.innerHTML = '<span class="attr-drag-handle" draggable="true">⠿</span>' +
      '<input type="text" class="attr-item-input" value="' + escAttr(lines[i]) + '" data-field="value">' +
      '<button class="btn btn-danger btn-sm" onclick="window.deleteAttrOption(this)">✕</button>';
    list.appendChild(div);
  }
  toast('已添加 ' + lines.length + ' 项，点击「保存全部修改」持久化');
};

window.deleteAttrOption = function(btn) {
  if (!confirm('确定删除此选项？')) return;
  var item = btn.closest('.attr-item');
  var id = item && item.dataset.id;
  if (!id) { item.remove(); return; }
  api('/admin/work-attributes/' + id, { method: 'DELETE' }).then(function() { toast('已删除'); item.remove(); }).catch(function(e) { toast(e.message || '删除失败', 'error'); });
};

window.getDragAfterElement = function(container, y) {
  var items = [...container.querySelectorAll('.attr-item:not(.dragging)')];
  return items.reduce(function(closest, child) {
    var box = child.getBoundingClientRect();
    var offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) return { offset: offset, element: child };
    return closest;
  }, { offset: Number.NEGATIVE_INFINITY }).element;
};

window.setupDragAndDrop = function() {
  document.querySelectorAll('.attr-list').forEach(function(list) {
    list.addEventListener('dragstart', function(e) {
      var item = e.target.closest('.attr-item');
      if (!item) return;
      e.dataTransfer.setData('text/plain', item.dataset.id || '');
      item.classList.add('dragging');
    });
    list.addEventListener('dragend', function(e) {
      var item = e.target.closest('.attr-item');
      if (item) item.classList.remove('dragging');
    });
    list.addEventListener('dragover', function(e) {
      e.preventDefault();
      var dragging = list.querySelector('.dragging');
      if (!dragging) return;
      var after = window.getDragAfterElement(list, e.clientY);
      if (after) { list.insertBefore(dragging, after); } else { list.appendChild(dragging); }
    });
  });
};

window.saveAllAttributes = function() {
  var promises = [];
  document.querySelectorAll('.attr-panel').forEach(function(panel) {
    var cat = panel.dataset.cat;
    var items = panel.querySelectorAll('.attr-item');
    items.forEach(function(item, idx) {
      var id = item.dataset.id;
      var value = item.querySelector('[data-field="value"]').value.trim();
      if (!value) return;
      if (id) {
        promises.push(api('/admin/work-attributes/' + id, { method: 'PUT', body: JSON.stringify({ category: cat, value: value, sort_order: idx }) }));
      } else {
        promises.push(api('/admin/work-attributes', { method: 'POST', body: JSON.stringify({ category: cat, value: value, sort_order: idx }) }));
      }
    });
  });
  if (!promises.length) { toast('没有修改', 'error'); return; }
  Promise.all(promises).then(function() { toast('全部已保存'); window.loadWorkAttributes(); }).catch(function(e) { toast('保存失败: ' + (e.message || e), 'error'); });
};

window.loadWorkAttributes();
