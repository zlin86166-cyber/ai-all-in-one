const DOWNLOAD_URL =
  'https://github.com/zlin86166-cyber/ai-all-in-one/releases/download/v0.2.0/AIHub-Windows.zip';
const REPOSITORY_URL = 'https://github.com/zlin86166-cyber/ai-all-in-one';

const features = [
  ['CLI 原生接入', 'Codex、Gemini 與 ChatGPT API 都從本機官方 CLI 啟動。'],
  ['多 AI 協作', '規劃、分工、並行、Peer Review 與成果彙整都在同一條任務時間線。'],
  ['專案與檔案', '切換不同專案，選取檔案範圍，預覽、修改、下載與匯入匯出。'],
  ['本機模型', '發現 Ollama 模型，並同步 Kimi／DeepSeek 官方 ≤50B 模型目錄。'],
  ['進度可追蹤', '即時顯示階段、進度、預估剩餘時間、預計與實際結束時間。'],
  ['權限透明', 'Workspace、Full 與 MAX-CLI 分級；帳號發布和高風險操作保留逐次確認。'],
];

export default function Home() {
  return (
    <main>
      <nav className="nav shell">
        <a className="brand" href="#top" aria-label="AI Hub 首頁">
          <span className="brandMark">AI</span>
          <span>AI Hub</span>
        </a>
        <div className="navMeta">
          <span className="statusDot" />
          <span>Windows release</span>
          <span className="version">v0.2.0</span>
        </div>
      </nav>

      <section className="hero shell" id="top">
        <div className="eyebrow"><span>●</span> LOCAL-FIRST AI OPERATOR</div>
        <h1>一個桌面，<br />指揮所有 AI。</h1>
        <p className="heroCopy">
          白色潔淨的 Windows 原生工作台，把 Codex、Gemini、ChatGPT、DeepSeek、Kimi
          與其他開源模型放進同一個可追蹤、可協作的工作流程。
        </p>
        <div className="actions">
          <a className="primary" href={DOWNLOAD_URL} download>
            <span>下載 Windows ZIP</span>
            <span aria-hidden="true">↓</span>
          </a>
          <a className="secondary" href={REPOSITORY_URL} target="_blank" rel="noreferrer">
            查看 GitHub 原始碼 ↗
          </a>
        </div>
        <p className="downloadNote">Windows 10/11 · x64 · 約 35 MB · ZIP 內含 SHA-256 清單</p>

        <div className="console" aria-label="AI Hub 執行能力摘要">
          <div className="consoleBar">
            <div className="windowDots"><i /><i /><i /></div>
            <span>AI HUB // OPERATOR CONSOLE</span>
            <span className="online">● READY</span>
          </div>
          <div className="consoleGrid">
            <div className="agents">
              <p className="consoleLabel">SELECTED AGENTS</p>
              {['Codex CLI', 'Gemini CLI', 'ChatGPT API CLI', 'deepseek-r1:7b'].map((agent, index) => (
                <div className="agent" key={agent}>
                  <span className={index === 1 ? 'idle' : ''}>●</span>
                  <strong>{agent}</strong>
                  <small>{index === 1 ? 'LOGIN' : 'READY'}</small>
                </div>
              ))}
            </div>
            <div className="runPanel">
              <div className="runHead"><span>WORK // 建立並驗證 Windows 發行版</span><b>78%</b></div>
              <div className="progress"><span /></div>
              <div className="timeline">
                <p><time>00:00</time><span>GitHub 主線同步完成</span><b>DONE</b></p>
                <p><time>00:18</time><span>多模型協作與檔案範圍驗證</span><b>DONE</b></p>
                <p className="active"><time>00:41</time><span>封裝、雜湊與最終自檢</span><b>RUNNING</b></p>
              </div>
              <div className="metrics"><span>ETA 01:12</span><span>END 17:20</span><span>MODE MAX-CLI</span></div>
            </div>
          </div>
        </div>
      </section>

      <section className="metricsBand">
        <div className="shell statGrid">
          <div><b>3</b><span>官方 CLI</span></div>
          <div><b>≤50B</b><span>模型上限</span></div>
          <div><b>10/10</b><span>封裝自檢</span></div>
          <div><b>Local</b><span>SQLite 對話資料</span></div>
        </div>
      </section>

      <section className="section shell">
        <div className="sectionHead">
          <p>CAPABILITIES</p>
          <h2>不是聊天視窗，<br />是完整的 AI 工作環境。</h2>
        </div>
        <div className="featureGrid">
          {features.map(([title, description], index) => (
            <article key={title}>
              <span>0{index + 1}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="installSection">
        <div className="shell installGrid">
          <div>
            <p className="sectionKicker">QUICK START</p>
            <h2>下載、解壓、開始工作。</h2>
            <p>不需要架設網頁伺服器。AI Hub 是直接在你的 Windows 電腦上執行的原生應用程式。</p>
          </div>
          <ol>
            <li><b>01</b><span><strong>下載 ZIP</strong>取得完整 Windows 發行包。</span></li>
            <li><b>02</b><span><strong>解壓縮</strong>保留包內所有 EXE 與 PowerShell 工具。</span></li>
            <li><b>03</b><span><strong>執行 setup.ps1</strong>安裝或更新官方 CLI 並建立桌面捷徑。</span></li>
            <li><b>04</b><span><strong>開啟 AI Hub</strong>選擇專案、AI 與檔案後開始工作。</span></li>
          </ol>
        </div>
      </section>

      <section className="requirements shell">
        <div>
          <p className="sectionKicker">REQUIREMENTS</p>
          <h2>先確認你的電腦。</h2>
        </div>
        <div className="reqTable">
          <p><span>作業系統</span><b>Windows 10 / 11 x64</b></p>
          <p><span>建議記憶體</span><b>16 GB 以上</b></p>
          <p><span>應用程式空間</span><b>2 GB 以上</b></p>
          <p><span>大型本機模型</span><b>另依模型與量化格式準備空間</b></p>
        </div>
      </section>

      <footer>
        <div className="shell footerInner">
          <div><strong>AI Hub</strong><p>Native multi-model operator for Windows.</p></div>
          <div className="footerLinks">
            <a href={DOWNLOAD_URL}>下載 v0.2.0</a>
            <a href={`${REPOSITORY_URL}/releases/tag/v0.2.0`} target="_blank" rel="noreferrer">Release notes</a>
            <a href={REPOSITORY_URL} target="_blank" rel="noreferrer">GitHub</a>
          </div>
        </div>
      </footer>
    </main>
  );
}
