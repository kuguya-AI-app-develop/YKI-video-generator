const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function field(value = "") {
  return { value, addEventListener() {}, replaceChildren(...children) { this.children = children; } };
}

function fixture() {
  const document = {
    getElementById: () => field(), querySelectorAll: () => [],
    createElement: () => field(), activeElement: null,
  };
  const context = vm.createContext({ document, setInterval() {}, fetch: () => new Promise(() => {}) });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8"), context);
  const versions = field("v001");
  const editor = {
    prompt: field("new prompt"), narration: field("第二版本旁白"),
    locked: { checked: false }, versions, status: {}, save: {}, retry: {}, preview: {},
    dirty: false, requestBusy: false, versionKey: "old",
    card: { contains: (element) => element === versions },
  };
  const shot = {
    id: "S01", prompt: "original prompt", narration: "原始旁白", locked: true,
    status: "completed", versions: [{ id: "v001" }, { id: "v002" }], selected_version: "v001",
  };
  document.activeElement = versions;
  Object.assign(context, { editor, shot });
  vm.runInContext('state.editors.set("S01", editor)', context);
  return { editor, shot, render: () => vm.runInContext("renderShot(shot, false)", context) };
}

test("selected history updates clean fields while the version selector keeps focus", () => {
  const { editor, render } = fixture();
  render();
  assert.equal(editor.narration.value, "原始旁白");
  assert.equal(editor.prompt.value, "original prompt");
  assert.equal(editor.locked.checked, true);
});

test("polling never overwrites unsaved editor changes", () => {
  const { editor, render } = fixture();
  editor.dirty = true;
  render();
  assert.equal(editor.narration.value, "第二版本旁白");
  assert.equal(editor.prompt.value, "new prompt");
  assert.equal(editor.locked.checked, false);
});

test("unchanged text is not reassigned, preserving textarea selection during polling", () => {
  const { editor, shot, render } = fixture();
  editor.card.contains = () => false;
  for (const key of ["prompt", "narration"]) {
    Object.defineProperty(editor[key], "value", {
      get: () => shot[key], set: () => assert.fail("Unchanged text must not reset the caret"),
    });
  }
  render();
});

test("a rejected history change restores the server-selected version even while focused", () => {
  const { editor, render } = fixture();
  editor.versions.value = "v002";
  render();
  assert.equal(editor.versions.value, "v001");
  assert.equal(editor.versions.children.length, 2);
});
