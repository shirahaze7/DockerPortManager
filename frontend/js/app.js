const API = '/api/services';

/**
 * APIからサービスデータを取得し、UIをレンダリングする
 */
async function loadData() {
  const btn = document.getElementById('btn-refresh');
  btn.classList.add('loading');
  btn.textContent = '↻ LOADING...';

  try {
    const res = await fetch(API);
    const data = await res.json();
    render(data);
  } catch (e) {
    document.getElementById('table-wrap').innerHTML = `
      <div class="empty-state">
        <div class="icon">✕</div>
        <p>API CONNECTION ERROR</p>
      </div>
    `;
  } finally {
    btn.classList.remove('loading');
    btn.textContent = '↻ REFRESH';
  }
}

/**
 * 取得したサービスデータをUIにレンダリング
 * @param {Object} data - APIからのレスポンスデータ
 */
function render(data) {
  const services = data.services || [];
  const active = services.filter(s => s.in_use).length;
  const idle = services.length - active;

  // 統計情報を更新
  document.getElementById('stat-total').textContent = services.length;
  document.getElementById('stat-active').textContent = active;
  document.getElementById('stat-idle').textContent = idle;
  document.getElementById('stat-files').textContent = data.compose_files_found || 0;
  document.getElementById('hdr-host').textContent = location.hostname;

  const wrap = document.getElementById('table-wrap');

  // サービスが存在しない場合は空状態を表示
  if (services.length === 0) {
    wrap.innerHTML = `
      <div class="empty-state">
        <div class="icon">◎</div>
        <p>NO COMPOSE FILES FOUND</p>
      </div>
    `;
    return;
  }

  // サービスをソート：起動中（in_use）を上位に、次にサービス名の昇順
  services.sort((a, b) => {
    // 1. 起動中のものを上位に
    if (b.in_use - a.in_use !== 0) {
      return b.in_use - a.in_use;
    }
    // 2. 同じ状態なら、サービス名の昇順
    return (a.service || '').localeCompare(b.service || '');
  });

  // サービスカードのHTMLを生成
  const cards = services.map((s, i) => {
    return `
      <div
        class="service-card ${s.in_use ? 'in-use' : ''} animate-in"
        style="animation-delay:${i * 30}ms"
      >
        <div class="card-top">
          <div>
            <div class="service-title">
              ${esc(s.service)}
            </div>
            <div class="service-sub">
              ${esc(s.compose_file)}
            </div>
          </div>
          <div class="status-badge ${s.in_use ? 'active' : 'idle'}">
            ${s.in_use ? 'ACTIVE' : 'IDLE'}
          </div>
        </div>

        <div class="port-box">
          <div class="port-label">
            HOST PORT
          </div>
          <div class="port-number">
            ${s.host_port || '—'}
          </div>
        </div>

        <div class="action-row">
          ${
            s.url
              ? `
                <a
                  class="open-btn ${s.in_use ? '' : 'disabled'}"
                  href="${s.url}"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  OPEN SERVICE
                </a>
              `
              : `
                <div class="open-btn disabled">
                  NO URL
                </div>
              `
          }

          <button
            type="button"
            class="open-btn ${s.in_use ? 'disabled' : ''}"
            ${s.in_use ? 'disabled' : ''}
            data-compose-file="${esc(s.compose_file)}"
            onclick="confirmStart(this.dataset.composeFile)"
          >
            開始
          </button>

          <button
            type="button"
            class="open-btn stop-btn ${s.in_use ? '' : 'disabled'}"
            ${s.in_use ? '' : 'disabled'}
            data-compose-file="${esc(s.compose_file)}"
            onclick="confirmStop(this.dataset.composeFile)"
          >
            終了
          </button>
        </div>
      </div>
    `;
  }).join('');

  // サービスグリッドを表示
  wrap.innerHTML = `
    <div class="service-grid">
      ${cards}
    </div>
  `;

  // エラーセクションをレンダリング
  const errSec = document.getElementById('errors-section');

  if (data.errors && data.errors.length > 0) {
    errSec.innerHTML = `
      <div
        class="section-header"
        style="margin-top:28px"
      >
        <h2>Parse Errors</h2>
      </div>

      <div class="error-list">
        ${data.errors.map(e => `
          <div class="error-item">
            <div class="err-file">
              ${esc(e.file)}
            </div>
            <div>
              ${esc(e.error)}
            </div>
          </div>
        `).join('')}
      </div>
    `;
  } else {
    errSec.innerHTML = '';
  }

  // 最終更新時刻を表示
  document.getElementById('timestamp').textContent =
    'LAST UPDATED: ' +
    new Date().toLocaleString('ja-JP');
}

/**
 * HTMLエスケープ：XSS対策
 * @param {string} s - エスケープする文字列
 * @returns {string} エスケープされた文字列
 */
function esc(s) {
  return String(s || '').replace(
    /[&<>"']/g,
    c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[c])
  );
}

/**
 * Docker Composeアクション（up/down）をサーバーに送信
 * @param {string} action - 実行するアクション（'up' または 'down'）
 * @param {string} compose_file - 対象のcompose-fileパス
 */
async function sendComposeAction(action, compose_file) {
  try {
    const res = await fetch(`/api/compose/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ compose_file })
    });

    let data = null;
    let text = null;
    try {
      text = await res.text();
      data = JSON.parse(text);
    } catch (err) {
      data = null;
    }

    // レスポンスの成功判定とアラート表示
    if (res.ok && data && data.success) {
      alert(action === 'up' ? '開始しました' : '終了しました');
    } else {
      const msg = (data && (data.error || data.stderr)) || text || `${res.status} ${res.statusText}`;
      alert('エラー: ' + msg);
    }
  } catch (e) {
    alert('Request error: ' + e.message);
  } finally {
    // 完了後、データを再読み込み
    loadData();
  }
}

/**
 * サービス開始の確認ダイアログと実行
 * @param {string} compose_file - 対象のcompose-fileパス
 */
function confirmStart(compose_file) {
  if (!confirm('このサービスを開始しますか？')) return;
  sendComposeAction('up', compose_file);
}

/**
 * サービス終了の確認ダイアログと実行
 * @param {string} compose_file - 対象のcompose-fileパス
 */
function confirmStop(compose_file) {
  if (!confirm('このサービスを終了しますか？')) return;
  sendComposeAction('down', compose_file);
}

// ============ 初期化 ============
loadData();

// 30秒ごとにデータを自動更新
setInterval(loadData, 30000);
