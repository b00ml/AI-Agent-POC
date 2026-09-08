"""
生成「启衡精密 AI 财务提效 POC · 解决方案设计」网页 PPT（瑞士国际主义 · IKB）。

基于 guizang-ppt-skill 的 template-swiss.html，替换标题与示例页为方案内容。
用法：python tools/build_solution_ppt.py
"""

import os

TARGET = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "doc", "solution_ppt", "index.html",
)
MOTION_ASSET_SRC = r"C:\Users\asus\.codex\skills\guizang-ppt-skill\assets\motion.min.js"
MOTION_ASSET_DST = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "doc", "solution_ppt", "assets", "motion.min.js",
)

SLIDES = r"""
<section class="slide accent" data-animate="hero" data-layout="S01">
  <div class="canvas-card">
    <canvas class="ascii-bg" aria-hidden="true"></canvas>
    <div class="chrome-min">
      <div class="l">启衡精密 AI 财务提效 POC · 解决方案设计</div>
      <div class="r">SWISS · 2026.08 · 01 / 13</div>
    </div>
    <div style="flex:1;padding:0;display:grid;grid-template-rows:auto 1fr auto;gap:2.6vh">
      <div data-anim="kicker" class="t-meta" style="color:rgba(255,255,255,.78);letter-spacing:.22em">SOLUTION DESIGN / 解决方案设计</div>
      <div data-anim="title" style="display:flex;align-items:center">
        <h1 style="font-family:var(--sans),var(--sans-zh);font-weight:200;font-size:min(8.4vw,15vh);line-height:.94;letter-spacing:-.025em;color:#fff;margin:0">让 AI 先读票,<br/>人做<span style="font-style:italic;font-weight:300">决定</span>。</h1>
      </div>
      <div data-anim="bottom" style="display:grid;grid-template-rows:auto auto;gap:1.6vh;border-top:1px solid rgba(255,255,255,.22);padding-top:2vh">
        <div data-anim="lead" class="lead" style="max-width:56ch;color:rgba(255,255,255,.86)">面向费用报销审核与发票稽核的智能预筛系统 —— 300 单积压变为「AI 预筛 + 人工聚焦复核」，判定以票面影像为准。</div>
        <div style="display:flex;justify-content:space-between;align-items:end">
          <div class="t-meta" style="color:rgba(255,255,255,.6)">FDE · 启衡精密财务部 · 2026-08</div>
          <div class="t-meta" style="color:rgba(255,255,255,.6)">→ swipe / arrow keys</div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="slide dark" data-animate="statement" data-layout="S03">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">业务问题 · 01 — 问题</div>
      <div class="r">SWISS · 02 / 13</div>
    </div>
    <h1 style="align-self:center;font-family:var(--sans),var(--sans-zh);font-weight:200;font-size:min(6.4vw,12vh);line-height:1.02;letter-spacing:-.03em;color:var(--paper)">300 张单据,<br/>压在<span style="font-style:italic;font-weight:300;color:var(--accent-bright)">一个人</span>身上。</h1>
    <div style="display:flex;justify-content:space-between;align-items:end;border-top:1px solid rgba(255,255,255,.22);padding-top:2vh;margin-top:auto">
      <div class="t-meta" style="color:rgba(255,255,255,.6)">费用会计周晓全量人工审核 · 系统只收单、不判断</div>
      <div class="t-meta" style="color:rgba(255,255,255,.6)">月均 250–300 单 · 审单 30–40 小时</div>
    </div>
  </div>
</section>

<section class="slide" data-animate="why-now" data-layout="S18">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">业务问题 · 02 — 为什么现在做</div>
      <div class="r">SWISS · 03 / 13</div>
    </div>
    <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:3vh 0 0">三个数字,说明现状</h2>
    <div class="why-now-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:3vw;margin-top:7vh">
      <div class="why-col">
        <span class="t-cat">BACKLOG</span>
        <h3 class="h-md" style="font-weight:400;margin:1.4vh 0">待审积压</h3>
        <p class="body-sm" style="font-size:max(15px,1vw);line-height:1.6;color:var(--text-secondary)">待审池 300 单；月底单量集中提交，审核排队，销售垫款等半个月。</p>
        <div class="why-num-bottom" style="font-family:var(--sans);font-weight:200;font-size:min(7vw,11vh);line-height:.95;letter-spacing:-.04em;margin-top:4vh">300</div>
      </div>
      <div class="why-col">
        <span class="t-cat">EFFORT</span>
        <h3 class="h-md" style="font-weight:400;margin:1.4vh 0">人工工时</h3>
        <p class="body-sm" style="font-size:max(15px,1vw);line-height:1.6;color:var(--text-secondary)">月审单 30–40 小时纯人工；简单单 3–5 分钟，差旅单 8–12 分钟。</p>
        <div class="why-num-bottom" style="font-family:var(--sans);font-weight:200;font-size:min(7vw,11vh);line-height:.95;letter-spacing:-.04em;margin-top:4vh">40h</div>
      </div>
      <div class="why-col">
        <span class="t-cat">RECONCILING</span>
        <h3 class="h-md" style="font-weight:400;margin:1.4vh 0">对账瓶颈</h3>
        <p class="body-sm" style="font-size:max(15px,1vw);line-height:1.6;color:var(--text-secondary)">银行流水 600–700 笔/月全手工比对，对账 3–4 天；三个月积压未核销。</p>
        <div class="why-num-bottom" style="font-family:var(--sans);font-weight:200;font-size:min(7vw,11vh);line-height:.95;letter-spacing:-.04em;margin-top:4vh;color:var(--accent)">3–4d</div>
      </div>
    </div>
  </div>
</section>

<section class="slide" data-animate="duo-mirror" data-layout="S08">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">方案思路 · 01 — 现状 vs 目标</div>
      <div class="r">SWISS · 04 / 13</div>
    </div>
    <div class="duo-compare" style="flex:1;display:grid;grid-template-columns:1fr 1px 1fr;gap:4vw;align-items:stretch">
      <div style="display:flex;flex-direction:column;justify-content:center">
        <span class="t-cat">BEFORE · 现状</span>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:2vh 0">逐单全审</h2>
        <ul style="display:flex;flex-direction:column;gap:1.6vh;list-style:none;padding:0;margin:0;font-size:max(16px,1.05vw);line-height:1.6;color:var(--text-secondary)">
          <li>· 人工翻票，抬头/税号/金额逐张比对</li>
          <li>· 住宿每晚单价手算，标准靠查表</li>
          <li>· 重复报销靠记忆，跨单查重做不到</li>
          <li>· 退单来回沟通，一单审两遍</li>
        </ul>
      </div>
      <span class="vrule" style="background:var(--grey-2)"></span>
      <div style="display:flex;flex-direction:column;justify-content:center">
        <span class="t-cat">AFTER · 目标</span>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:2vh 0;color:var(--accent)">AI 预筛</h2>
        <ul style="display:flex;flex-direction:column;gap:1.6vh;list-style:none;padding:0;margin:0;font-size:max(16px,1.05vw);line-height:1.6;color:var(--text-secondary)">
          <li>· OCR 读票面，票面优先于系统录入</li>
          <li>· 10 条规则自动判定，理由可追溯</li>
          <li>· 全量发票索引，跨单重复自动查重</li>
          <li>· 周晓只复核存疑单（≤30%）</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<section class="slide" data-animate="field-notes" data-layout="S16">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">项目范围 · 本阶段做与不做</div>
      <div class="r">SWISS · 05 / 13</div>
    </div>
    <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:3vh 0 5vh">范围清晰,先验证价值</h2>
    <div class="brief-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:1.4vw">
      <div class="brief-card card-fill" style="padding:3vh 2vw;min-height:24vh;display:flex;flex-direction:column;justify-content:space-between">
        <div style="font-size:max(17px,1.15vw);font-weight:500">M2 智能报销审核</div>
        <div class="t-meta">300 单结论回写 ERP，形成人工复核队列</div>
      </div>
      <div class="brief-card card-fill" style="padding:3vh 2vw;min-height:24vh;display:flex;flex-direction:column;justify-content:space-between">
        <div style="font-size:max(17px,1.15vw);font-weight:500">M3 发票异常稽核</div>
        <div class="t-meta">全量 23,461 张：重复/抬头/税号/税率</div>
      </div>
      <div class="brief-card card-accent" style="padding:3vh 2vw;min-height:24vh;display:flex;flex-direction:column;justify-content:space-between;color:var(--accent-on)">
        <div style="font-size:max(17px,1.15vw);font-weight:500">AI 复核助手</div>
        <div class="t-meta" style="color:rgba(255,255,255,.82)">规则+大模型双轨，分歧自动转存疑</div>
      </div>
      <div class="brief-card card-fill" style="padding:3vh 2vw;min-height:24vh;display:flex;flex-direction:column;justify-content:space-between">
        <div style="font-size:max(17px,1.15vw);font-weight:500">M4 银行对账（加分）</div>
        <div class="t-meta">201 笔自动匹配（63.8%），114 笔待人工认领</div>
      </div>
      <div class="brief-card card-fill" style="padding:3vh 2vw;min-height:24vh;display:flex;flex-direction:column;justify-content:space-between">
        <div style="font-size:max(17px,1.15vw);font-weight:500">本阶段不做</div>
        <div class="t-meta">数据库直连 · 全自动秒批 · ERP 前端改造 · 付款自动化</div>
      </div>
      <div class="brief-card card-fill" style="padding:3vh 2vw;min-height:24vh;display:flex;flex-direction:column;justify-content:space-between">
        <div style="font-size:max(17px,1.15vw);font-weight:500">交付形态</div>
        <div class="t-meta">Vue(5173) + FastAPI(8000) + Streamlit(8501) · Docker 一键部署</div>
      </div>
    </div>
  </div>
</section>

<section class="slide dark" data-animate="timeline-walk" data-layout="S11">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">核心用户流程 · 员工到账时间缩短</div>
      <div class="r">SWISS · 06 / 13</div>
    </div>
    <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:3vh 0 0;color:var(--paper)">一条链,五个环节</h2>
    <div class="timeline-h" style="position:relative;margin-top:16vh">
      <span class="tl-h-axis" style="position:absolute;top:1.1vh;left:2%;right:2%;height:1px;background:rgba(255,255,255,.3)"></span>
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:1vw">
        <div class="tl-h-node" style="display:flex;flex-direction:column;align-items:flex-start;gap:1.6vh">
          <span class="num" style="font-family:var(--mono);font-size:14px;color:rgba(255,255,255,.6)">01</span>
          <span class="dot" style="width:8px;height:8px;background:var(--paper)"></span>
          <span class="lbl" style="font-size:max(16px,1vw);color:var(--paper);font-weight:400">员工提单<br/><span style="font-size:max(14px,.9vw);color:rgba(255,255,255,.6)">上传票据影像</span></span>
        </div>
        <div class="tl-h-node" style="display:flex;flex-direction:column;align-items:flex-start;gap:1.6vh">
          <span class="num" style="font-family:var(--mono);font-size:14px;color:rgba(255,255,255,.6)">02</span>
          <span class="dot" style="width:8px;height:8px;background:var(--accent-bright)"></span>
          <span class="lbl" style="font-size:max(16px,1vw);color:var(--paper);font-weight:400">AI 预审<br/><span style="font-size:max(14px,.9vw);color:rgba(255,255,255,.6)">OCR + 10 条规则</span></span>
        </div>
        <div class="tl-h-node" style="display:flex;flex-direction:column;align-items:flex-start;gap:1.6vh">
          <span class="num" style="font-family:var(--mono);font-size:14px;color:rgba(255,255,255,.6)">03</span>
          <span class="dot" style="width:8px;height:8px;background:var(--accent-bright)"></span>
          <span class="lbl" style="font-size:max(16px,1vw);color:var(--paper);font-weight:400">意见回写 ERP<br/><span style="font-size:max(14px,.9vw);color:rgba(255,255,255,.6)">不改单据状态</span></span>
        </div>
        <div class="tl-h-node" style="display:flex;flex-direction:column;align-items:flex-start;gap:1.6vh">
          <span class="num" style="font-family:var(--mono);font-size:14px;color:rgba(255,255,255,.6)">04</span>
          <span class="dot" style="width:8px;height:8px;background:var(--accent-bright)"></span>
          <span class="lbl" style="font-size:max(16px,1vw);color:var(--paper);font-weight:400">周晓复核<br/><span style="font-size:max(14px,.9vw);color:rgba(255,255,255,.6)">只聚焦存疑单</span></span>
        </div>
        <div class="tl-h-node" style="display:flex;flex-direction:column;align-items:flex-start;gap:1.6vh">
          <span class="num" style="font-family:var(--mono);font-size:14px;color:rgba(255,255,255,.6)">05</span>
          <span class="dot" style="width:8px;height:8px;background:var(--paper)"></span>
          <span class="lbl" style="font-size:max(16px,1vw);color:var(--paper);font-weight:400">人工放行付款<br/><span style="font-size:max(14px,.9vw);color:rgba(255,255,255,.6)">最终决定在人</span></span>
        </div>
      </div>
    </div>
    <div style="margin-top:9vh;border-top:1px solid rgba(255,255,255,.22);padding-top:2.4vh;display:flex;justify-content:space-between;align-items:end">
      <div style="font-size:max(16px,1.05vw);color:var(--paper);font-weight:400">改善环节：审核从「逐单全审」变为「聚焦存疑单」，周晓复核量下降至 ≤30%。</div>
      <div class="t-meta" style="color:rgba(255,255,255,.6)">→ 下一步：付款环节提速</div>
    </div>
  </div>
</section>

<section class="slide" data-animate="system-diagram" data-layout="S17">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">系统设计 · 分层架构</div>
      <div class="r">SWISS · 07 / 13</div>
    </div>
    <div class="grid-2-7-5" style="display:grid;grid-template-columns:1fr 1.4fr;gap:4vw;align-items:start">
      <div>
        <span class="t-cat">ARCHITECTURE</span>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:2vh 0 2.4vh">四层,各司其职</h2>
        <p class="body-sm" style="font-size:max(16px,1vw);line-height:1.65;color:var(--text-secondary)">接入层走开放平台 API；引擎层本地 OCR + 确定性规则；复核层制度知识库 + 大模型双轨；呈现层三入口交付。</p>
      </div>
      <div style="display:flex;flex-direction:column;gap:1.6vh">
        <div class="card-fill" style="padding:2.6vh 2vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:center">
          <span class="t-meta" style="font-weight:600">接入层</span>
          <div style="font-size:max(16px,1vw)">开放平台 API · X-Api-Key · 游标分页 · 429 限流退避 · 最小权限</div>
        </div>
        <div class="card-fill" style="padding:2.6vh 2vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:center">
          <span class="t-meta" style="font-weight:600">引擎层</span>
          <div style="font-size:max(16px,1vw)">本地 PaddleOCR 票面提取 · 10 条规则 · 全量发票索引 · 特批豁免</div>
        </div>
        <div class="card-fill" style="padding:2.6vh 2vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:center">
          <span class="t-meta" style="font-weight:600">复核层</span>
          <div style="font-size:max(16px,1vw)">制度知识库（33 条款）· DeepSeek 独立复核 · 分歧转存疑</div>
        </div>
        <div class="card-fill" style="padding:2.6vh 2vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:center">
          <span class="t-meta" style="font-weight:600">呈现层</span>
          <div style="font-size:max(16px,1vw)">Vue 主界面 · FastAPI · Streamlit/CLI · 三栏票据比对 · 人工复核</div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="slide" data-animate="four-cards" data-layout="S19">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">系统设计 · 技术选择</div>
      <div class="r">SWISS · 08 / 13</div>
    </div>
    <div style="width:100%;height:1px;background:var(--accent);margin:3vh 0"></div>
    <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:0 0 6vh">四个关键选择</h2>
    <div class="four-cards" style="display:grid;grid-template-columns:repeat(4,1fr);gap:2vw">
      <div class="fc-col">
        <div class="t-meta" style="margin-bottom:1.6vh">— 01 / OCR</div>
        <h3 class="h-md" style="font-weight:400;margin:0 0 1.6vh">本地 PaddleOCR</h3>
        <p class="body-sm" style="font-size:max(15px,.98vw);line-height:1.6;color:var(--text-secondary)">发票图片不出域；票面要素优先于系统录入，识别失败显式标注。</p>
      </div>
      <div class="fc-col">
        <div class="t-meta" style="margin-bottom:1.6vh">— 02 / RULES</div>
        <h3 class="h-md" style="font-weight:400;margin:0 0 1.6vh">确定性规则引擎</h3>
        <p class="body-sm" style="font-size:max(15px,.98vw);line-height:1.6;color:var(--text-secondary)">10 条违规可评测可回归；30 单公开样例 F1=1.0，理由可追溯。</p>
      </div>
      <div class="fc-col">
        <div class="t-meta" style="margin-bottom:1.6vh">— 03 / AI</div>
        <h3 class="h-md" style="font-weight:400;margin:0 0 1.6vh">DeepSeek 复核</h3>
        <p class="body-sm" style="font-size:max(15px,.98vw);line-height:1.6;color:var(--text-secondary)">结合制度知识库独立复核，分歧自动转 FLAG；外发字段已申报。</p>
      </div>
      <div class="fc-col">
        <div class="t-meta" style="margin-bottom:1.6vh">— 04 / DELIVERY</div>
        <h3 class="h-md" style="font-weight:400;margin:0 0 1.6vh">三入口交付</h3>
        <p class="body-sm" style="font-size:max(15px,.98vw);line-height:1.6;color:var(--text-secondary)">Vue + FastAPI + CLI 复用同一 core；Docker 一键部署，可迁移。</p>
      </div>
    </div>
  </div>
</section>

<section class="slide" data-animate="three-forces" data-layout="S13">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">系统设计 · 数据来源与接入</div>
      <div class="r">SWISS · 09 / 13</div>
    </div>
    <div class="grid-2-9" style="display:grid;grid-template-columns:1fr 1.6fr;gap:4vw;align-items:stretch">
      <div style="display:flex;flex-direction:column;justify-content:center;gap:2vh">
        <span class="t-cat">DATA & INTEGRATION</span>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:0">三类数据<br/>一套接入</h2>
      </div>
      <div class="sub-card-stack" style="display:flex;flex-direction:column;gap:1.8vh">
        <article class="card-fill" style="padding:3vh 2.4vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:start">
          <i data-lucide="database" style="width:22px;height:22px;color:var(--accent)"></i>
          <div>
            <h4 style="font-weight:500;margin:0 0 .8vh">ERP 开放平台</h4>
            <p style="font-size:max(15px,.98vw);line-height:1.55;color:var(--text-secondary);margin:0">报销单 / 审批 / 附件 / 差旅标准 / 发票台账，X-Api-Key 鉴权，最小权限。</p>
          </div>
        </article>
        <article class="card-fill" style="padding:3vh 2.4vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:start">
          <i data-lucide="book-open" style="width:22px;height:22px;color:var(--accent)"></i>
          <div>
            <h4 style="font-weight:500;margin:0 0 .8vh">制度知识库</h4>
            <p style="font-size:max(15px,.98vw);line-height:1.55;color:var(--text-secondary);margin:0">报销办法 V3.2 / 发票合规指引 / 审批矩阵 / 供应商办法，33 条款可检索。</p>
          </div>
        </article>
        <article class="card-fill" style="padding:3vh 2.4vw;display:grid;grid-template-columns:auto 1fr;gap:1.6vw;align-items:start">
          <i data-lucide="landmark" style="width:22px;height:22px;color:var(--accent)"></i>
          <div>
            <h4 style="font-weight:500;margin:0 0 .8vh">银行流水 + 应收台账</h4>
            <p style="font-size:max(15px,.98vw);line-height:1.55;color:var(--text-secondary);margin:0">GBK CSV × receivables，户名+金额+唯一候选匹配，宁缺毋滥。</p>
          </div>
        </article>
      </div>
    </div>
  </div>
</section>

<section class="slide dark" data-animate="loop-form" data-layout="S14">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">风险与人工介入 · 人机协作闭环</div>
      <div class="r">SWISS · 10 / 13</div>
    </div>
    <div class="loop-diagram" style="display:grid;grid-template-columns:1fr 1fr;gap:4vw;align-items:center;flex:1">
      <div class="loop-steps" style="display:flex;flex-direction:column;gap:2.4vh">
        <div class="t-meta" style="color:rgba(255,255,255,.6);letter-spacing:.2em">HUMAN-IN-THE-LOOP</div>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:0;color:var(--paper)">AI 给意见,<br/>人做<span style="font-style:italic;font-weight:300;color:var(--accent-bright)">决定</span></h2>
        <div style="display:flex;flex-direction:column;gap:1.6vh;margin-top:2vh">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:1.4vw;align-items:start;border-top:1px solid rgba(255,255,255,.22);padding-top:1.8vh">
            <span class="num" style="font-family:var(--mono);font-size:14px;color:var(--accent-bright)">01</span>
            <p style="margin:0;font-size:max(16px,1vw);color:var(--paper);font-weight:400">规则 + AI 双轨预审，结论与理由写回 ERP 复核队列</p>
          </div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:1.4vw;align-items:start;border-top:1px solid rgba(255,255,255,.22);padding-top:1.8vh">
            <span class="num" style="font-family:var(--mono);font-size:14px;color:var(--accent-bright)">02</span>
            <p style="margin:0;font-size:max(16px,1vw);color:var(--paper);font-weight:400">分歧单据自动转 FLAG，交周晓/财务经理人工复核</p>
          </div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:1.4vw;align-items:start;border-top:1px solid rgba(255,255,255,.22);padding-top:1.8vh">
            <span class="num" style="font-family:var(--mono);font-size:14px;color:var(--accent-bright)">03</span>
            <p style="margin:0;font-size:max(16px,1vw);color:var(--paper);font-weight:400">人工放行后，反馈沉淀回规则与知识库，闭环迭代</p>
          </div>
        </div>
      </div>
      <div class="loop-svg" style="display:flex;flex-direction:column;align-items:center;gap:3vh">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1vw;width:100%">
          <div class="card-fill" style="padding:2.4vh 1.2vw;text-align:center">
            <i data-lucide="scan-search" style="width:20px;height:20px;color:var(--paper)"></i>
            <div style="margin-top:1vh;font-size:max(14px,.95vw);color:var(--paper)">预审</div>
          </div>
          <div class="card-fill" style="padding:2.4vh 1.2vw;text-align:center">
            <i data-lucide="flag" style="width:20px;height:20px;color:var(--accent-bright)"></i>
            <div style="margin-top:1vh;font-size:max(14px,.95vw);color:var(--paper)">存疑</div>
          </div>
          <div class="card-fill" style="padding:2.4vh 1.2vw;text-align:center">
            <i data-lucide="user-check" style="width:20px;height:20px;color:var(--paper)"></i>
            <div style="margin-top:1vh;font-size:max(14px,.95vw);color:var(--paper)">放行</div>
          </div>
        </div>
        <div style="width:1px;height:4vh;background:var(--accent-bright)"></div>
        <div class="t-meta" style="color:rgba(255,255,255,.6)">反馈沉淀 → 规则与知识库更新 → 回到预审</div>
      </div>
    </div>
  </div>
</section>

<section class="slide" data-animate="duo-mirror" data-layout="S08">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">风险与人工介入 · 边界</div>
      <div class="r">SWISS · 11 / 13</div>
    </div>
    <div class="duo-compare" style="flex:1;display:grid;grid-template-columns:1fr 1px 1fr;gap:4vw;align-items:stretch">
      <div style="display:flex;flex-direction:column;justify-content:center">
        <span class="t-cat">HUMAN CONFIRM · 人工介入点</span>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:2vh 0">四道人工闸</h2>
        <ul style="display:flex;flex-direction:column;gap:1.6vh;list-style:none;padding:0;margin:0;font-size:max(16px,1.05vw);line-height:1.6;color:var(--text-secondary)">
          <li>· 最终放行：状态流转必须人工点击</li>
          <li>· FLAG/REJECT 单：周晓逐单复核</li>
          <li>· AI 复核分歧：规则 vs 大模型不一致时</li>
          <li>· M4 待认领：名称/金额无法唯一确认的流水</li>
        </ul>
      </div>
      <span class="vrule" style="background:var(--grey-2)"></span>
      <div style="display:flex;flex-direction:column;justify-content:center">
        <span class="t-cat">RISKS · 主要风险</span>
        <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:2vh 0;color:var(--accent)">四类风险</h2>
        <ul style="display:flex;flex-direction:column;gap:1.6vh;list-style:none;padding:0;margin:0;font-size:max(16px,1.05vw);line-height:1.6;color:var(--text-secondary)">
          <li>· 漏判 > 误判：漏放违规单代价最高，宁可多标存疑</li>
          <li>· OCR 识别率：劣质影像用 FLAG 降级，不臆断</li>
          <li>· 数据出域：默认本地识别，云端模型须申报</li>
          <li>· 制度版本：V3.2 现行，旧版 V2.1 已废止</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<section class="slide" data-animate="progression" data-layout="S20">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">价值 · 可量化结果</div>
      <div class="r">SWISS · 12 / 13</div>
    </div>
    <h2 class="h-xl" style="font-family:var(--sans),var(--sans-zh);font-weight:200;margin:3vh 0 5vh">省下的时间,折成钱</h2>
    <div class="stacked-ledger" style="display:flex;flex-direction:column">
      <div class="ledger-row" style="display:grid;grid-template-columns:1fr auto;gap:2vw;align-items:baseline;border-bottom:1px solid var(--grey-2);padding:2.6vh 0">
        <div style="font-size:max(16px,1.05vw);color:var(--text-secondary)">月审单耗时（纯人工）</div>
        <div style="display:flex;align-items:baseline;gap:1vw"><span class="ledger-num" style="font-family:var(--sans);font-weight:200;font-size:min(6vw,9vh);line-height:.9;letter-spacing:-.03em">↓50%</span><span class="t-meta">30–40h → 15–20h</span></div>
      </div>
      <div class="ledger-row" style="display:grid;grid-template-columns:1fr auto;gap:2vw;align-items:baseline;border-bottom:1px solid var(--grey-2);padding:2.6vh 0">
        <div style="font-size:max(16px,1.05vw);color:var(--text-secondary)">银行对账周期</div>
        <div style="display:flex;align-items:baseline;gap:1vw"><span class="ledger-num" style="font-family:var(--sans);font-weight:200;font-size:min(6vw,9vh);line-height:.9;letter-spacing:-.03em">3–4d→1d</span><span class="t-meta">自动匹配 201 笔（63.8%）</span></div>
      </div>
      <div class="ledger-row" style="display:grid;grid-template-columns:1fr auto;gap:2vw;align-items:baseline;border-bottom:1px solid var(--grey-2);padding:2.6vh 0">
        <div style="font-size:max(16px,1.05vw);color:var(--text-secondary)">300 单待审池</div>
        <div style="display:flex;align-items:baseline;gap:1vw"><span class="ledger-num" style="font-family:var(--sans);font-weight:200;font-size:min(6vw,9vh);line-height:.9;letter-spacing:-.03em">100%</span><span class="t-meta">已回写可复核</span></div>
      </div>
      <div class="ledger-row" style="display:grid;grid-template-columns:1fr auto;gap:2vw;align-items:baseline;border-bottom:2px solid var(--accent);padding:2.6vh 0">
        <div style="font-size:max(16px,1.05vw);color:var(--text-secondary)">30 单公开样例评测</div>
        <div style="display:flex;align-items:baseline;gap:1vw"><span class="ledger-num" style="font-family:var(--sans);font-weight:200;font-size:min(6vw,9vh);line-height:.9;letter-spacing:-.03em;color:var(--accent)">F1 1.0</span><span class="t-meta">驳回判定 · 本地 OCR</span></div>
      </div>
    </div>
    <div class="t-meta" style="margin-top:3vh;color:var(--text-helper)">下一步：部署验收 → 全量评测 → 二期扩展应收/应付审核与付款自动化</div>
  </div>
</section>

<section class="slide split" data-animate="split-statement" data-layout="S10">
  <div class="canvas-card">
    <div class="split-half">
      <div class="half b-accent" style="padding:5.6vh 3.6vw 4.4vh;justify-content:space-between;position:relative;overflow:hidden">
        <canvas class="ascii-bg" aria-hidden="true"></canvas>
        <div class="chrome-min" style="margin-bottom:0;position:relative;z-index:1">
          <div class="l">13 / 13</div>
          <div class="r">CLOSING</div>
        </div>
        <div data-anim="manifesto" style="display:flex;flex-direction:column;gap:2vh;position:relative;z-index:1">
          <div class="t-meta" style="color:rgba(255,255,255,.78);letter-spacing:.22em;margin-bottom:1.6vh">MANIFESTO</div>
          <h2 style="font-family:var(--sans),var(--sans-zh);font-size:min(7.4vw,13vh);line-height:.94;letter-spacing:-.025em;font-weight:200;color:#fff">让 AI 先读票,<br/>人做<span style="font-style:italic;font-weight:300">决定</span>。</h2>
          <div style="font-family:var(--sans),var(--sans-zh);font-size:max(14px,1vw);line-height:1.6;color:rgba(255,255,255,.82);font-weight:400;max-width:34ch;margin-top:1.4vh">AI 负责读、算、查；人负责核、批、放。用 POC 验证价值，再谈投入。</div>
        </div>
        <div data-anim="signature" style="display:flex;justify-content:space-between;align-items:end;border-top:1px solid rgba(255,255,255,.22);padding-top:2vh;position:relative;z-index:1">
          <div class="t-meta" style="color:rgba(255,255,255,.62)">FDE · 启衡精密</div>
          <div class="t-meta" style="color:rgba(255,255,255,.62)">2026.08</div>
        </div>
      </div>
      <div class="half" style="padding:5.6vh 3.6vw 4.4vh;justify-content:space-between">
        <div class="chrome-min">
          <div class="l">TAKEAWAYS</div>
          <div class="r">03 RULES</div>
        </div>
        <div data-anim="rules" style="display:flex;flex-direction:column;gap:0">
          <div style="display:grid;grid-template-columns:auto 1fr;gap:2vw;align-items:start;padding:2.6vh 0;border-top:1px solid var(--border-subtle)">
            <div style="font-family:var(--sans);font-weight:200;font-size:min(4vw,7vh);line-height:.9;color:var(--text-primary)">01</div>
            <div>
              <h3 style="font-family:var(--sans),var(--sans-zh);font-weight:400;font-size:max(18px,1.7vw);line-height:1.2;letter-spacing:-.015em;color:var(--text-primary);margin-bottom:1vh">300 单已回写</h3>
              <p style="font-family:var(--sans),var(--sans-zh);font-size:max(15px,.92vw);line-height:1.6;color:var(--text-secondary);font-weight:400;margin:0">结论与理由进入 ERP 人工复核队列，周晓可直接操作。</p>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:2vw;align-items:start;padding:2.6vh 0;border-top:1px solid var(--border-subtle)">
            <div style="font-family:var(--sans);font-weight:200;font-size:min(4vw,7vh);line-height:.9;color:var(--text-primary)">02</div>
            <div>
              <h3 style="font-family:var(--sans),var(--sans-zh);font-weight:400;font-size:max(18px,1.7vw);line-height:1.2;letter-spacing:-.015em;color:var(--text-primary);margin-bottom:1vh">规则 + AI 双轨</h3>
              <p style="font-family:var(--sans),var(--sans-zh);font-size:max(15px,.92vw);line-height:1.6;color:var(--text-secondary);font-weight:400;margin:0">规则保证可评测可回归，大模型复核兜住规则盲区。</p>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:auto 1fr;gap:2vw;align-items:start;padding:2.6vh 0;border-top:1px solid var(--border-subtle);border-bottom:2px solid var(--accent)">
            <div style="font-family:var(--sans);font-weight:200;font-size:min(4vw,7vh);line-height:.9;color:var(--accent)">03</div>
            <div>
              <h3 style="font-family:var(--sans),var(--sans-zh);font-weight:400;font-size:max(18px,1.7vw);line-height:1.2;letter-spacing:-.015em;color:var(--accent);margin-bottom:1vh">本地优先,数据不出域</h3>
              <p style="font-family:var(--sans),var(--sans-zh);font-size:max(15px,.92vw);line-height:1.6;color:var(--text-secondary);font-weight:400;margin:0">默认本地 OCR；云端模型显式启用并申报，守住数据安全底线。</p>
            </div>
          </div>
        </div>
        <div data-anim="foot" class="t-meta" style="color:var(--text-helper);text-align:right">→ 完 · END OF SOLUTION DESIGN</div>
      </div>
    </div>
  </div>
</section>
"""


def main() -> None:
    with open(TARGET, "r", encoding="utf-8") as f:
        html = f.read()

    # 替换标题
    old_title = "[必填] 替换为 PPT 标题 · Deck Title"
    if old_title in html:
        html = html.replace(old_title, "启衡精密 AI 财务提效 POC · 解决方案设计")

    # 定位 deck 容器、示例 section 区间（从第一个示例 section 到 deck 关闭前最后一个 </section>）
    deck_idx = html.find('<div id="deck">')
    start = html.find('<section class="slide accent" data-animate="hero"')
    if start < 0:
        start = html.find('<section class="slide accent"')
    nav_idx = html.find('<div id="nav">')
    if deck_idx < 0 or start < 0 or nav_idx < 0:
        raise RuntimeError("未找到模板示例区边界")
    end = html.rfind("</section>", 0, nav_idx)
    if end < start:
        raise RuntimeError("示例区定位异常")

    # 保留 deck 开标签，丢弃其后的引导注释与示例页，替换为方案内容
    html = html[: deck_idx + len('<div id="deck">')] + "\n" + SLIDES.strip() + "\n" + html[end + len("</section>"):]

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(html)

    # 复制离线动效库（模板相对引用 assets/motion.min.js）
    if os.path.exists(MOTION_ASSET_SRC):
        os.makedirs(os.path.dirname(MOTION_ASSET_DST), exist_ok=True)
        with open(MOTION_ASSET_SRC, "rb") as src, open(MOTION_ASSET_DST, "wb") as dst:
            dst.write(src.read())
        print("已复制动效库:", MOTION_ASSET_DST)
    print("已生成:", TARGET)


if __name__ == "__main__":
    main()
