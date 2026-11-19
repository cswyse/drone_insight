/* Dashboard data admin: live totals for the market grid and revenue-split lists. */
(function () {
  function num(v) { var n = parseFloat(String(v).replace(/,/g, "")); return isNaN(n) ? 0 : n; }

  var grid = document.getElementById("market-grid");
  if (grid) {
    var totals = grid.querySelectorAll("[data-total]");
    var update = function () {
      var sums = [];
      grid.querySelectorAll("tbody input[data-year]").forEach(function (inp) {
        var y = +inp.getAttribute("data-year");
        sums[y] = (sums[y] || 0) + num(inp.value);
      });
      totals.forEach(function (td) {
        var v = sums[+td.getAttribute("data-total")] || 0;
        td.textContent = v ? v.toLocaleString(undefined, { maximumFractionDigits: v >= 100 ? 0 : 1 }) : "0";
      });
    };
    grid.addEventListener("input", update);
    update();
  }

  document.querySelectorAll("[data-split]").forEach(function (box) {
    var out = box.querySelector("[data-sum]");
    var update = function () {
      var t = 0, any = false;
      box.querySelectorAll("input").forEach(function (i) { var v = num(i.value); if (v) any = true; t += v; });
      t = Math.round(t * 10) / 10;
      out.textContent = "Total " + t + "%";
      out.className = "pct-sum " + (!any ? "" : Math.abs(t - 100) < 0.5 ? "ok" : "off");
    };
    box.addEventListener("input", update);
    update();
  });
})();

// Company form: add another product row
(function () {
  var btn = document.getElementById("prod-add"), table = document.getElementById("prod-table");
  if (!btn || !table) return;
  btn.addEventListener("click", function () {
    var body = table.tBodies[0], last = body.rows[body.rows.length - 1], n = body.rows.length;
    var row = last.cloneNode(true);
    Array.prototype.forEach.call(row.querySelectorAll("input"), function (inp) {
      inp.name = inp.name.replace(/^prod_\d+_/, "prod_" + n + "_");
      inp.value = ""; inp.classList.remove("bad"); inp.title = "";
      inp.setAttribute("aria-label", inp.getAttribute("aria-label").replace(/Product \d+/, "Product " + (n + 1)));
    });
    body.appendChild(row);
    document.getElementById("prod-n").value = n + 1;
    row.querySelector("input").focus();
  });
})();
