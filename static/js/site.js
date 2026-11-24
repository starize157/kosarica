(function () {
  document.querySelectorAll("[data-swap-form]").forEach(function (form) {
    var max = Number(form.getAttribute("data-max"));
    var note = form.querySelector("[data-swap-note]");
    var preview = form.querySelector("[data-preview]");
    var base = JSON.parse(form.getAttribute("data-base"));
    var names = JSON.parse(form.getAttribute("data-names"));
    var selects = Array.prototype.slice.call(form.querySelectorAll("select[data-swap]"));

    function chosenIds() {
      return base.map(function (id) {
        var sel = form.querySelector('select[name="swap_' + id + '"]');
        return sel && sel.value ? sel.value : id;
      });
    }

    function used() {
      return selects.filter(function (sel) { return Boolean(sel.value); }).length;
    }

    function render() {
      if (note) note.textContent = used() + " / " + max + " menjav";
      if (preview) {
        preview.textContent = chosenIds().map(function (id) { return names[id] || id; }).join(" · ");
      }
    }

    selects.forEach(function (sel) {
      sel.addEventListener("change", function () {
        var values = selects.map(function (item) { return item.value; }).filter(Boolean);
        var duplicate = sel.value && values.filter(function (value) { return value === sel.value; }).length > 1;
        var over = used() > max;
        if (duplicate || over) {
          sel.value = "";
          render();
          if (note) {
            note.textContent = duplicate
              ? "Te zelenjave ne moreš dodati dvakrat."
              : "Največ " + max + " menjav.";
          }
          return;
        }
        render();
      });
    });

    render();
  });
})();
