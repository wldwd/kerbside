// Kerbside: shared script for the news pages. Loads the stories,
// builds the filters and cards, and handles search and "Continue?".

const PAGE_SIZE = 60;
const NEW_HOURS = 48;

const state = {
  tags: new Set(),
  regions: new Set(),
  query: "",
  shown: PAGE_SIZE,
};
let data = null;
let tagGroup = {}; // tag name -> group index (for colours)

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs))
    node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const opts = { day: "numeric", month: "short" };
  if (date.getFullYear() !== new Date().getFullYear())
    opts.year = "numeric";
  return date.toLocaleDateString("en-AU", opts);
}

function isNew(iso) {
  return (
    iso && Date.now() - new Date(iso).getTime() < NEW_HOURS * 3600 * 1000
  );
}

function safeLink(url) {
  return /^https?:\/\//i.test(url) ? url : "#";
}

/* ---------- Filtering ---------- */

function matches(story, skip) {
  if (
    skip !== "tags" &&
    state.tags.size &&
    !story.tags.some((t) => state.tags.has(t))
  )
    return false;
  if (
    skip !== "regions" &&
    state.regions.size &&
    !story.regions.some((r) => state.regions.has(r))
  )
    return false;
  if (state.query) {
    const text =
      `${story.title} ${story.summary} ${story.source}`.toLowerCase();
    if (!text.includes(state.query)) return false;
  }
  return true;
}

/* ---------- Building the filter chips ---------- */

function makeChip(label, set, extraClass) {
  const chip = el("button", {
    type: "button",
    class: `chip ${extraClass}`,
    "aria-pressed": "false",
  });
  chip.dataset.value = label;
  chip.append(label, el("span", { class: "count" }));
  chip.addEventListener("click", () => {
    set.has(label) ? set.delete(label) : set.add(label);
    state.shown = PAGE_SIZE;
    render();
  });
  return chip;
}

function buildFilters() {
  data.groups.forEach((group, i) => {
    const fieldset = el("fieldset");
    fieldset.append(el("legend", {}, group.name));
    const chips = el("div", { class: "chips" });
    group.tags.forEach((tag) => {
      tagGroup[tag] = i;
      chips.append(makeChip(tag, state.tags, `g${i} tag-chip`));
    });
    fieldset.append(chips);
    $("groups").append(fieldset);
  });
  data.regions.forEach((region) =>
    $("regions").append(makeChip(region, state.regions, "region-chip"))
  );
}

// Counts show how many stories each chip would add, given the other filters
function updateChips() {
  const tagCounts = {},
    regionCounts = {};
  for (const story of data.stories) {
    if (matches(story, "tags"))
      story.tags.forEach((t) => (tagCounts[t] = (tagCounts[t] || 0) + 1));
    if (matches(story, "regions"))
      story.regions.forEach(
        (r) => (regionCounts[r] = (regionCounts[r] || 0) + 1)
      );
  }
  document.querySelectorAll(".tag-chip").forEach((chip) => {
    const value = chip.dataset.value,
      count = tagCounts[value] || 0;
    chip.setAttribute("aria-pressed", state.tags.has(value));
    chip.querySelector(".count").textContent = count;
    chip.disabled = count === 0 && !state.tags.has(value);
  });
  document.querySelectorAll(".region-chip").forEach((chip) => {
    const value = chip.dataset.value,
      count = regionCounts[value] || 0;
    chip.setAttribute("aria-pressed", state.regions.has(value));
    chip.querySelector(".count").textContent = count;
    chip.disabled = count === 0 && !state.regions.has(value);
  });
}

/* ---------- Story cards ---------- */

function makeCard(story) {
  const card = el("li", { class: "card pixel-box" });
  const firstGroup = story.tags
    .map((t) => tagGroup[t])
    .find((g) => g !== undefined);
  if (firstGroup !== undefined) card.classList.add(`g${firstGroup}`);

  const meta = el("div", { class: "card-meta" });
  meta.append(el("span", { class: "source" }, story.source));
  if (story.published)
    meta.append(
      el(
        "time",
        { datetime: story.published },
        formatDate(story.published)
      )
    );
  card.append(meta);

  const heading = el("h2");
  if (isNew(story.published)) {
    heading.append(
      el(
        "span",
        { class: "new", title: "Published in the last 2 days" },
        "NEW"
      )
    );
  }
  heading.append(
    el(
      "a",
      { href: safeLink(story.link), target: "_blank", rel: "noopener" },
      story.title
    )
  );
  card.append(heading);

  if (story.summary)
    card.append(el("p", { class: "snippet" }, story.summary));

  const tags = el("div", { class: "card-tags" });
  story.tags.forEach((t) =>
    tags.append(el("span", { class: `chip g${tagGroup[t] ?? ""}` }, t))
  );
  story.regions.forEach((r) =>
    tags.append(el("span", { class: "chip region" }, r))
  );
  if (tags.childElementCount) card.append(tags);

  return card;
}

/* ---------- Page update ---------- */

function render() {
  const results = data.stories.filter((s) => matches(s));
  const list = $("stories");
  list.replaceChildren(...results.slice(0, state.shown).map(makeCard));

  const filtered = state.tags.size || state.regions.size || state.query;
  $("result-count").textContent = filtered
    ? `${results.length} of ${data.stories.length} stories match`
    : `Showing all ${data.stories.length} stories, newest first`;
  $("clear").hidden = !filtered;
  $("empty").hidden = results.length > 0;
  const remaining = results.length - state.shown;
  $("more").hidden = remaining <= 0;
  if (remaining > 0) {
    $("more").querySelector("small").textContent = `Load ${Math.min(
      remaining,
      PAGE_SIZE
    )} more stories`;
  }
  updateChips();
}

function clearFilters() {
  state.tags.clear();
  state.regions.clear();
  state.query = "";
  state.shown = PAGE_SIZE;
  $("search").value = "";
  render();
}

function init(json) {
  data = json;
  // Newest first; undated stories last
  data.stories.sort((a, b) =>
    (b.published || "").localeCompare(a.published || "")
  );

  $("site-title").textContent = data.title;
  document.title = data.title;

  $("site-title").dataset.text = data.title;
  const stats = $("stats");
  stats.append(
    el("dt", {}, "STORIES"),
    el("dd", {}, String(data.stories.length).padStart(5, "0")),
    el("dt", {}, "UPDATED"),
    el("dd", {}, formatDate(data.updated).toUpperCase())
  );

  buildFilters();
  // Topic filters start open on wider screens, closed on phones
  $("topics").open = window.matchMedia("(min-width: 700px)").matches;

  let timer;
  $("search").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.query = e.target.value.trim().toLowerCase();
      state.shown = PAGE_SIZE;
      render();
    }, 150);
  });
  $("clear").addEventListener("click", clearFilters);
  $("empty-clear").addEventListener("click", clearFilters);
  $("more").addEventListener("click", () => {
    state.shown += PAGE_SIZE;
    render();
  });

  render();
}

// Each page names its data file in <body data-feed="...">
const FEED = document.body.dataset.feed || "stories.json";

fetch(FEED, { cache: "no-cache" })
  .then((response) => {
    if (!response.ok)
      throw new Error(`${FEED} returned ${response.status}`);
    return response.json();
  })
  .then(init)
  .catch((error) => {
    const box = $("empty");
    box.hidden = false;
    box.replaceChildren(
      "Stories could not be loaded (",
      error.message,
      "). If you opened this file directly, start a local server with ",
      el("code", {}, "python -m http.server --directory docs"),
      " and open http://localhost:8000."
    );
  });
