/* ── Chat JS ──────────────────────────────────────────────── */

let currentConversationId = null;
let currentObjective = null;
let isStreaming = false;

// ── Sidebar ──────────────────────────────────────────────────

async function loadConversations() {
  const res = await fetch("/conversations");
  const convs = await res.json();
  const list = document.getElementById("conversation-list");
  list.innerHTML = "";
  convs.forEach((c) => {
    const el = document.createElement("div");
    el.className =
      "sidebar-item" + (c.id === currentConversationId ? " active" : "");
    el.onclick = () => loadConversation(c.id);

    const title = document.createElement("div");
    title.className = "sidebar-item-title";
    title.textContent = c.title;
    el.appendChild(title);

    if (c.objective) {
      const obj = document.createElement("div");
      obj.className = "sidebar-item-objective";
      obj.textContent =
        c.objective.substring(0, 60) + (c.objective.length > 60 ? "…" : "");
      el.appendChild(obj);
    }

    // Delete button
    const del = document.createElement("button");
    del.className = "sidebar-item-delete";
    del.textContent = "✕";
    del.title = "Delete chat";
    del.onclick = (e) => {
      e.stopPropagation();
      deleteConversation(c.id);
    };
    el.appendChild(del);

    list.appendChild(el);
  });
}

async function loadConversation(id) {
  currentConversationId = id;
  history.replaceState(null, "", "/ui/chat/" + id);
  await loadConversations(); // refresh active state

  // Load messages
  const res = await fetch(`/conversations/${id}/messages`);
  const msgs = await res.json();

  const container = document.getElementById("messages");
  container.innerHTML = "";

  // Get conversation info for objective
  const convsRes = await fetch("/conversations");
  const convs = await convsRes.json();
  const conv = convs.find((c) => c.id === id);
  if (conv && conv.objective) {
    currentObjective = conv.objective;
    document.getElementById("objective-text").textContent = conv.objective;
    document.getElementById("objective-banner").style.display = "flex";
  } else {
    currentObjective = null;
    document.getElementById("objective-banner").style.display = "none";
  }

  // Render messages (skip tool messages, they're internal)
  msgs.forEach((m) => {
    if (m.role === "user") {
      appendMessage("user", m.content);
    } else if (m.role === "assistant" && m.content && !m.tool_calls) {
      appendMessage("assistant", m.content);
    }
    // tool messages and assistant messages with tool_calls are hidden from UI
  });

  scrollToBottom();
}

async function deleteConversation(id) {
  if (!confirm("Delete this conversation?")) return;
  await fetch(`/conversations/${id}`, { method: "DELETE" });
  if (currentConversationId === id) {
    currentConversationId = null;
    document.getElementById("messages").innerHTML = "";
    document.getElementById("objective-banner").style.display = "none";
    history.replaceState(null, "", "/ui/chat");
  }
  loadConversations();
}

// ── New Chat Modal ───────────────────────────────────────────

function showNewChatModal() {
  document.getElementById("new-chat-modal").style.display = "flex";
  document.getElementById("new-chat-objective").focus();
}

function hideNewChatModal(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById("new-chat-modal").style.display = "none";
  document.getElementById("new-chat-objective").value = "";
}

async function createChat(e) {
  e.preventDefault();
  const objective =
    document.getElementById("new-chat-objective").value.trim() || null;
  const res = await fetch("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New Chat", objective }),
  });
  const conv = await res.json();
  hideNewChatModal();
  await loadConversation(conv.id);
}

// ── Objective editing ────────────────────────────────────────

async function editObjective() {
  const newObj = prompt("Edit chat objective:", currentObjective || "");
  if (newObj === null) return;
  await fetch(`/conversations/${currentConversationId}/objective`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective: newObj }),
  });
  currentObjective = newObj;
  if (newObj) {
    document.getElementById("objective-text").textContent = newObj;
    document.getElementById("objective-banner").style.display = "flex";
  } else {
    document.getElementById("objective-banner").style.display = "none";
  }
  loadConversations();
}

// ── Message rendering ────────────────────────────────────────

function appendMessage(role, content) {
  const container = document.getElementById("messages");
  const wrapper = document.createElement("div");
  wrapper.className = `msg msg-${role}`;

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = renderMarkdown(content || "");

  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  return bubble;
}

function appendToolStatus(toolName) {
  const container = document.getElementById("messages");
  const pill = document.createElement("div");
  pill.className = "tool-status";
  const labels = {
    get_daily_digest: "Fetching daily digest…",
    search_episodes: "Searching episodes…",
    get_episode_detail: "Loading episode details…",
    list_podcasts: "Listing podcasts…",
    add_podcast: "Adding podcast…",
    remove_podcast: "Removing podcast…",
    set_podcast_category: "Setting category…",
  };
  pill.textContent = labels[toolName] || `Running ${toolName}…`;
  container.appendChild(pill);
  return pill;
}

function scrollToBottom() {
  const container = document.getElementById("messages");
  container.scrollTop = container.scrollHeight;
}

// ── Markdown (rich formatting) ───────────────────────────────

function renderMarkdown(text) {
  if (!text) return "";

  // Escape HTML
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Horizontal rules
  html = html.replace(/^---$/gm, '<hr class="md-hr">');

  // Headings
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h4">$1</h5>');
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h3">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h2">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h1">$1</h2>');

  // Blockquotes — collect consecutive &gt; lines into a single block
  html = html.replace(/(^&gt; .+(?:\n&gt;.*)*)/gm, function (match) {
    const inner = match
      .replace(/^&gt; ?/gm, "")
      .replace(/\n{2,}/g, "<br><br>")
      .replace(/\n/g, "<br>");
    return '<blockquote class="md-quote">' + inner + "</blockquote>";
  });

  // Inline: bold, italic, code, score badges
  // Dual score: **[8/10] Title** · Relevance: 6/10
  html = html.replace(
    /\*\*\[(\d+)\/10\]\s*(.+?)\*\*\s*·\s*Relevance:\s*(\d+)\/10/g,
    '<span class="md-score-line"><span class="md-score" data-score="$1">$1</span> <strong>$2</strong> <span class="md-relevance" data-score="$3">⎯ $3<small>/10 relevance</small></span></span>',
  );
  // Single score fallback (no objective)
  html = html.replace(
    /\*\*\[(\d+)\/10\]\s*(.+?)\*\*/g,
    '<span class="md-score-line"><span class="md-score" data-score="$1">$1</span> <strong>$2</strong></span>',
  );
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");

  // Numbered lists
  html = html.replace(/((?:^\d+\. .+\n?)+)/gm, function (match) {
    const items = match.trim().split("\n");
    const lis = items
      .map((item) => "<li>" + item.replace(/^\d+\.\s*/, "") + "</li>")
      .join("");
    return '<ol class="md-ol">' + lis + "</ol>";
  });

  // Unordered lists
  html = html.replace(/((?:^- .+\n?)+)/gm, function (match) {
    const items = match.trim().split("\n");
    const lis = items
      .map((item) => "<li>" + item.replace(/^- /, "") + "</li>")
      .join("");
    return '<ul class="md-ul">' + lis + "</ul>";
  });

  // Paragraphs
  html = html.replace(/\n{2,}/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");

  // Clean up consecutive blockquotes
  html = html.replace(
    /<\/blockquote>\s*<blockquote class="md-quote">/g,
    "<br><br>",
  );

  // Colorize listen score badges
  html = html.replace(/class="md-score" data-score="(\d+)"/g, function (_, s) {
    const n = parseInt(s);
    const cls = n >= 7 ? "high" : n >= 4 ? "mid" : "low";
    return 'class="md-score md-score-' + cls + '" data-score="' + s + '"';
  });
  // Colorize relevance badges
  html = html.replace(/class="md-relevance" data-score="(\d+)"/g, function (_, s) {
    const n = parseInt(s);
    const cls = n >= 7 ? "high" : n >= 4 ? "mid" : "low";
    return 'class="md-relevance md-rel-' + cls + '" data-score="' + s + '"';
  });

  return "<p>" + html + "</p>";
}

// ── Send message ─────────────────────────────────────────────

async function sendMessage(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg || isStreaming) return;

  input.value = "";
  input.style.height = "auto";
  isStreaming = true;
  document.getElementById("send-btn").disabled = true;

  // Show user message
  appendMessage("user", msg);
  scrollToBottom();

  // Create conversation if none selected
  let convId = currentConversationId;
  if (!convId) {
    const res = await fetch("/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "New Chat", objective: null }),
    });
    const conv = await res.json();
    convId = conv.id;
    currentConversationId = convId;
    history.replaceState(null, "", "/ui/chat/" + convId);
  }

  // Stream response
  let assistantBubble = null;
  let fullText = "";
  let activeTool = null;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: convId, message: msg }),
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6);
        if (data === "[DONE]") continue;

        try {
          const event = JSON.parse(data);

          if (event.type === "meta") {
            currentConversationId = event.conversation_id;
            history.replaceState(null, "", "/ui/chat/" + event.conversation_id);
          } else if (event.type === "tool") {
            // Remove previous tool pill if any
            if (activeTool) activeTool.remove();
            activeTool = appendToolStatus(event.name);
            scrollToBottom();
          } else if (event.type === "text") {
            // Remove tool status when text starts
            if (activeTool) {
              activeTool.remove();
              activeTool = null;
            }
            if (!assistantBubble) {
              assistantBubble = appendMessage("assistant", "");
            }
            fullText += event.content;
            assistantBubble.innerHTML = renderMarkdown(fullText);
            scrollToBottom();
          }
        } catch {
          // skip parse errors
        }
      }
    }
  } catch (err) {
    if (!assistantBubble) {
      assistantBubble = appendMessage("assistant", "");
    }
    assistantBubble.innerHTML =
      '<span style="color: var(--red);">Error: ' + err.message + "</span>";
  }

  if (activeTool) activeTool.remove();
  isStreaming = false;
  document.getElementById("send-btn").disabled = false;
  loadConversations(); // refresh sidebar titles
}

// ── Auto-resize textarea ─────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("chat-input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 150) + "px";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("chat-form").requestSubmit();
    }
  });
  loadConversations();
});
