import assert from "node:assert/strict";
import { test } from "node:test";

import { APP_CSS, APP_JS, INDEX_HTML } from "../assets.ts";

function idsDeclaredInHtml(): Set<string> {
	return new Set([...INDEX_HTML.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1] ?? ""));
}

test("every element the script looks up exists in the markup", () => {
	const declared = idsDeclaredInHtml();
	const referenced = [...APP_JS.matchAll(/\bel\("([^"]+)"\)/g)].map((match) => match[1] ?? "");

	assert.ok(referenced.length > 15, `expected the script to wire up the dashboard, found ${referenced.length} lookups`);
	const missing = referenced.filter((id) => !declared.has(id));
	assert.deepEqual(missing, [], `script references ids that the markup never defines: ${missing.join(", ")}`);
});

test("every css class used by the markup and script is defined in the stylesheet", () => {
	const defined = new Set([...APP_CSS.matchAll(/\.([a-z][a-z0-9-]*)/g)].map((match) => match[1] ?? ""));
	const fromMarkup = [...INDEX_HTML.matchAll(/\sclass="([^"]+)"/g)].flatMap((match) => (match[1] ?? "").split(/\s+/));
	const fromScript = [...APP_JS.matchAll(/className = "([^"]+)"/g)].flatMap((match) => (match[1] ?? "").split(/\s+/));

	const missing = [...new Set([...fromMarkup, ...fromScript])].filter((name) => name && !defined.has(name));
	assert.deepEqual(missing, [], `classes used without a style rule: ${missing.join(", ")}`);
});

test("markup carries no inline script or style that its own policy would block", () => {
	assert.doesNotMatch(INDEX_HTML, /<script(?![^>]*\ssrc=)/);
	assert.doesNotMatch(INDEX_HTML, /<style/);
	assert.doesNotMatch(INDEX_HTML, /\sstyle="/);
	assert.doesNotMatch(INDEX_HTML, /\son[a-z]+="/);
});

test("assets reference no third-party origin", () => {
	for (const [name, asset] of [
		["html", INDEX_HTML],
		["css", APP_CSS],
		["js", APP_JS],
	] as const) {
		assert.doesNotMatch(asset, /https?:\/\//, `${name} must not load anything remote`);
	}
});

test("session values reach the page as text rather than markup", () => {
	assert.doesNotMatch(APP_JS, /innerHTML/);
	assert.doesNotMatch(APP_JS, /outerHTML/);
	assert.doesNotMatch(APP_JS, /insertAdjacentHTML/);
	assert.match(APP_JS, /textContent/);
});

test("the page states that costs are provider-reported and never estimated", () => {
	assert.match(INDEX_HTML, /nothing is estimated/i);
});

test("wide tables use keyboard-reachable scroll regions and controls meet the touch target", () => {
	assert.equal((INDEX_HTML.match(/class="table-scroll"/g) ?? []).length, 3);
	assert.match(INDEX_HTML, /class="table-scroll" tabindex="0" role="region"/);
	assert.match(APP_CSS, /\.table-scroll\s*\{[^}]*overflow-x:\s*auto/s);
	assert.match(APP_CSS, /button, input, select\s*\{[^}]*min-height:\s*44px/s);
});

test("the chart exposes equivalent daily data without animating layout", () => {
	assert.match(INDEX_HTML, /<caption>Daily spend data<\/caption>/);
	assert.match(INDEX_HTML, /id="chart-data-body"/);
	assert.match(APP_JS, /chartDataBody\.append\(dataRow\)/);
	assert.doesNotMatch(APP_CSS, /transition:\s*height/);
	assert.doesNotMatch(APP_JS, /bar\.style\.height/);
	assert.match(APP_CSS, /transition:\s*transform/);
});

test("theme control communicates its current mode and validates persisted values", () => {
	assert.match(INDEX_HTML, />Theme: Auto<\/button>/);
	assert.match(APP_JS, /function updateThemeControl\(mode\)/);
	assert.match(APP_JS, /THEME_ORDER\.includes\(saved\)/);
	assert.match(APP_JS, /Switch to " \+ nextMode \+ " theme/);
});

test("model and project tables are complete and sessions expand progressively", () => {
	assert.doesNotMatch(APP_JS, /models\.slice\(0,\s*14\)/);
	assert.doesNotMatch(APP_JS, /projects\.slice\(0,\s*14\)/);
	assert.doesNotMatch(APP_JS, /rows\.slice\(0,\s*200\)/);
	assert.match(INDEX_HTML, /id="sessions-more"/);
	assert.match(APP_JS, /visibleSessionLimit \+= SESSION_PAGE_SIZE/);
	assert.match(APP_JS, /nodes\.sessionsMore\.hidden = shown >= rows\.length/);
});
