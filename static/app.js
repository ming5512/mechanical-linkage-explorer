const form = document.querySelector("#search-form");
const queryInput = document.querySelector("#query-input");
const submitButton = document.querySelector("#submit-button");
const statusBox = document.querySelector("#status");
const resultBox = document.querySelector("#result");
const resultTitle = document.querySelector("#result-title");
const cacheBadge = document.querySelector("#cache-badge");
const previewImage = document.querySelector("#preview-image");
const sourceLink = document.querySelector("#source-link");
const chips = document.querySelectorAll(".chip");

function setStatus(message, tone = "info") {
  statusBox.textContent = message;
  statusBox.dataset.tone = tone;
  statusBox.style.background = tone === "error" ? "#fee2e2" : "#eef2ff";
  statusBox.style.color = tone === "error" ? "#991b1b" : "#3730a3";
}

function showResult(payload) {
  resultTitle.textContent = payload.query;
  cacheBadge.textContent = payload.cached ? "来自缓存" : "新下载";
  previewImage.src = `${payload.mediaPath}?t=${Date.now()}`;
  previewImage.alt = `${payload.query} 动图`;
  sourceLink.href = payload.sourceUrl;
  resultBox.classList.remove("hidden");
}

async function searchAnimation(query) {
  submitButton.disabled = true;
  resultBox.classList.add("hidden");
  setStatus(`正在搜索 "${query}" 的动图资源，请稍候...`);

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });

    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "搜索失败");

    showResult(payload);
    setStatus(
      payload.cached
        ? `已命中缓存，正在显示 "${query}" 的动图。`
        : `已完成抓取并缓存，正在显示 "${query}" 的动图。`
    );
  } catch (error) {
    setStatus(error.message || "发生未知错误。", "error");
  } finally {
    submitButton.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) { setStatus("请输入机械结构名称。", "error"); return; }
  searchAnimation(query);
});

chips.forEach((chip) => {
  chip.addEventListener("click", () => {
    queryInput.value = chip.dataset.query;
    searchAnimation(chip.dataset.query);
  });
});
