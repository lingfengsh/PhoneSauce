/* PS-ENGINE 前端回归 —— 第三步「其他参数的基准引擎」渲染逻辑（2.0 新增）。

本机无浏览器自动化，故用 node 的 vm 加载**真实源文件** `ui/app.js` 的相关函数，
DOM / api 全部打桩。断言集中在 4 处：
  1. 有对象 → 对应引擎 chip 可选；无对象 → chip 置灰（disabled）
  2. 当前基准若不在可用集合 → 自动回退到第一个可用引擎（默认 praat）
  3. 三个引擎 F0 都没有 / 两个引擎共振峰都没有 → 出警示 + 禁用「开始批量处理」
  4. 只勾了 F0/共振峰本身（无下游参数）时，不因缺基础数据而禁用

运行：
    node tests/engine_ui_regress.js
*/
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const SRC = path.join(__dirname, "..", "ui", "app.js");

/* ---------------- DOM 打桩 ---------------- */
const els = {};
function fakeEl(sel) {
  const el = {
    __sel: sel, style: {}, dataset: {}, children: [],
    className: "", innerHTML: "", textContent: "", value: "", checked: false,
    disabled: false, width: 0, height: 0, tagName: "DIV",
    classList: {
      _s: function () { return String(el.className || "").split(/\s+/).filter(Boolean); },
      contains: function (c) { return this._s().indexOf(c) >= 0; },
      add: function (c) { if (!this.contains(c)) el.className = (el.className ? el.className + " " : "") + c; },
      remove: function (c) { el.className = this._s().filter(x => x !== c).join(" "); },
      toggle: function (c, f) { const on = (f === undefined) ? !this.contains(c) : !!f; on ? this.add(c) : this.remove(c); return on; },
    },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    appendChild: function (c) { el.children.push(c); return c; },
    addEventListener: function () {}, removeEventListener: function () {},
    getAttribute: function (k) { return el.dataset[k] || null; },
    setAttribute: function (k, v) { el.dataset[k] = v; },
    insertAdjacentHTML: function (_, h) { el.innerHTML += h; },
    getContext: function () { return null; },
    focus: function () {}, blur: function () {}, click: function () {},
  };
  return el;
}
// $() 传的是 "#id" 形式的选择器；统一按原样做 key，保证「测试里取的元素」
// 与「被测代码 $() 取的元素」是同一个对象。
function getEl(sel) {
  if (!els[sel]) els[sel] = fakeEl(sel);
  return els[sel];
}

/* ---------------- 上下文 ---------------- */
let apiReply = {};
const apiCalls = [];
const sandbox = {
  console,
  window: { addEventListener: function () {}, dispatchEvent: function () {}, scrollTo: function () {} },
  document: {
    querySelector: getEl,
    querySelectorAll: function () { return []; },
    getElementById: getEl,
    createElement: function () { return fakeEl("created"); },
    addEventListener: function () {},
    body: { insertAdjacentHTML: function () {}, classList: { add: function () {}, remove: function () {} } },
  },
  location: { hash: "" },
  history: { replaceState: function () {} },
  localStorage: { getItem: function () { return null; }, setItem: function () {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: function () {},
  Math, Date, JSON, Object, Array, String, Number, Boolean, RegExp, Error,
  Promise, Map, Set, isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
  fetch: function () { return Promise.resolve({ ok: true, json: function () { return Promise.resolve(apiReply); } }); },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

/* ---------------- 加载源文件（截取到 init() 之前，避免自动执行） ---------------- */
let code = fs.readFileSync(SRC, "utf8");
// 去掉末尾的 init() 自执行（若有），改为手动调用需要测的函数
code = code.replace(/^\s*init\(\);\s*$/m, "");
// 导出被测函数
const HOOK = `
  globalThis.__T = {
    renderBaseEngine: renderBaseEngine, renderEngineGroup: renderEngineGroup,
    needsBaseForSelection: needsBaseForSelection, syncRunButtons: syncRunButtons,
    labelOf: labelOf,
    setState: function (s) { Object.assign(state, s); },
    getState: function () { return state; },
    ENGINE_META: ENGINE_META,
  };
`;
code += HOOK;
vm.runInContext(code, sandbox, { filename: "app.js" });
const T = sandbox.__T;

/* ---------------- 断言 ---------------- */
let pass = 0, fail = 0;
function ok(cond, msg) { if (cond) { pass++; } else { fail++; console.log("  ✗ " + msg); } }
function eq(a, b, msg) { ok(a === b, msg + "（实际 " + JSON.stringify(a) + "，期望 " + JSON.stringify(b) + "）"); }

console.log("[1] 有对象→可选，无对象→置灰");
(function () {
  getEl("#f0BaseOpts"); getEl("#fmtBaseOpts");
  getEl("#f0BaseNote"); getEl("#fmtBaseNote");
  getEl("#baseEngineHint"); getEl("#baseEngineWarn"); getEl("#baseEngineCard");
  T.setState({
    engineAvail: {
      ok: true, total: 3,
      f0: { praat: 3, snack: 0, straight: 0 },
      formant: { praat: 3, snack: 0 },
      f0_any: true, formant_any: true,
    },
    values: { f0BaseEngine: "praat", formantBaseEngine: "praat", cpp: 1 },
  });
  T.renderBaseEngine();
  const html = getEl("#f0BaseOpts").innerHTML;
  ok(html.indexOf('data-eng="praat"') >= 0, "praat 选项已渲染");
  ok(html.indexOf('data-eng="snack"') >= 0, "snack 选项已渲染");
  ok(html.indexOf('data-eng="straight"') >= 0, "straight 选项已渲染");
  ok(/data-eng="snack"[^>]*disabled/.test(html), "snack 无对象→置灰");
  ok(/data-eng="straight"[^>]*disabled/.test(html), "straight 无对象→置灰");
  ok(!/data-eng="praat"[^>]*disabled/.test(html), "praat 有对象→可选");
})();

console.log("[2] 当前基准不可用→自动回退");
(function () {
  T.setState({
    engineAvail: {
      ok: true, total: 3,
      f0: { praat: 0, snack: 2, straight: 0 },
      formant: { praat: 3, snack: 0 },
      f0_any: true, formant_any: true,
    },
    values: { f0BaseEngine: "praat", formantBaseEngine: "praat", cpp: 1 },  // praat 无对象
  });
  T.renderBaseEngine();
  eq(T.getState().values.f0BaseEngine, "snack", "praat 不可用→回退到唯一可用的 snack");
})();

console.log("[3] 基础数据全无→警示 + 禁用批量");
(function () {
  T.setState({
    engineAvail: {
      ok: true, total: 3,
      f0: { praat: 0, snack: 0, straight: 0 },
      formant: { praat: 0, snack: 0 },
      f0_any: false, formant_any: false,
    },
    values: { f0BaseEngine: "praat", formantBaseEngine: "praat", cpp: 1 },
  });
  T.renderBaseEngine();
  const w = getEl("#baseEngineWarn");
  ok(w.innerHTML.indexOf("需要先算") >= 0, "出警示条");
  ok(!w.className.includes("hidden"), "警示条可见");
})();

console.log("[4] 只勾 F0/共振峰本身→不拦");
(function () {
  T.setState({
    engineAvail: { ok: true, total: 3, f0: { praat: 0, snack: 0, straight: 0 }, formant: { praat: 0, snack: 0 }, f0_any: false, formant_any: false },
    values: { pitch: 1, formant1: 1, cpp: 0, hnr_05: 0, soe: 0, intensity: 0 },
  });
  eq(T.needsBaseForSelection(), false, "只勾基础项→不需要基准");
})();

console.log("[5] 勾下游参数→需要基准");
(function () {
  T.setState({ values: { cpp: 1 } });
  eq(T.needsBaseForSelection(), true, "勾 CPP→需要 F0 基准");
  T.setState({ values: { cpp: 0, hnr_05: 1 } });
  eq(T.needsBaseForSelection(), true, "勾 HNR→需要 F0 基准");
  T.setState({ values: { cpp: 0, hnr_05: 0, ha_h1c: 1 } });
  eq(T.needsBaseForSelection(), true, "勾 H1c→需要 F0 基准");
  T.setState({ values: { ha_h1c: 0, bw1: 1 } });
  eq(T.needsBaseForSelection(), false, "只勾带宽（不在 F0 下游清单）→不触发（由后端 fmt 校验兜底）");
})();

console.log("[6] 自动回退的基准：praat 有了对象就回到 praat（用户报的「审核完成仍灰」）");
(function () {
  // 场景复现：目录里先有 STRAIGHT 对象（VS 界面算过）、praat 还没有 →
  // 基准被自动顶成 straight。之后审核完成写出 .Pitch → 必须回到 praat。
  T.setState({
    engineAvail: {
      ok: true, total: 3,
      f0: { praat: 0, snack: 0, straight: 3 },
      formant: { praat: 0, snack: 3 },
      f0_any: true, formant_any: true,
    },
    values: { f0BaseEngine: "praat", formantBaseEngine: "praat", cpp: 1 },
    baseEngineAuto: {},
  });
  T.renderBaseEngine();
  eq(T.getState().values.f0BaseEngine, "straight", "praat 缺→自动顶成 straight");
  eq(T.getState().baseEngineAuto.f0, true, "该值标记为自动（不是用户选的）");
  eq(T.getState().values.formantBaseEngine, "snack", "共振峰同样自动顶成 snack");

  // 审核完成：measure/ 里出现 .Pitch / .Formant
  T.setState({
    engineAvail: {
      ok: true, total: 3,
      f0: { praat: 3, snack: 0, straight: 3 },
      formant: { praat: 3, snack: 3 },
      f0_any: true, formant_any: true,
    },
  });
  T.renderBaseEngine();
  eq(T.getState().values.f0BaseEngine, "praat", "praat 出现→F0 基准回到 praat");
  eq(T.getState().values.formantBaseEngine, "praat", "praat 出现→共振峰基准回到 praat");
  ok(!/data-eng="praat"[^>]*disabled/.test(getEl("#f0BaseOpts").innerHTML), "praat chip 不再置灰");
})();

console.log("[7] 用户自己选的引擎：praat 后来出现也不改回去");
(function () {
  T.setState({
    engineAvail: {
      ok: true, total: 3,
      f0: { praat: 3, snack: 3, straight: 0 },
      formant: { praat: 3, snack: 3 },
      f0_any: true, formant_any: true,
    },
    values: { f0BaseEngine: "snack", formantBaseEngine: "snack", cpp: 1 },
    baseEngineAuto: {},   // 空 = 当前值是用户点的
  });
  T.renderBaseEngine();
  eq(T.getState().values.f0BaseEngine, "snack", "显式选择吃住，不被自动回退逻辑覆盖");
  eq(T.getState().values.formantBaseEngine, "snack", "共振峰同理");
})();

console.log("");
console.log(fail === 0 ? "全部通过：" + pass + " 项" : "失败 " + fail + " / 通过 " + pass);
process.exit(fail === 0 ? 0 : 1);
