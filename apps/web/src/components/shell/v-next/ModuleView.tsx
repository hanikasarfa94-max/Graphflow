"use client";

// v-next ModuleView — Rail detail-page renderer per spec §4d.
//
// Maps a moduleView ActiveView ('projectView'/'taskView'/'knowledgeView'/
// 'orgView'/'auditView') to the corresponding prototype-shape card grid
// from data.ts. v1 ships static cards matching the prototype's content
// (per spec §4d: "v1 wiring just glues existing detail data into the
// module-view card layout — no new BE endpoints needed for this slice").
//
// Replacing static placeholder rows with real data from existing
// /api/projects/{id}/state, /api/perf, /api/kb/* endpoints is a
// follow-up slice — Phase 3 wiring per detail kind.

import { useTranslations } from "next-intl";

import type { ActiveView } from "./AppShellClient";

import styles from "./ModuleView.module.css";

interface CardRow {
  title: string;
  meta: string;
}

interface ModuleCardData {
  title: string;
  body?: string;
  rows?: CardRow[];
}

interface ModuleViewSpec {
  title: string;
  subtitle: string;
  action?: string;
  cards: ModuleCardData[];
  twoColumn?: boolean;
}

// Static seeds match prototype data.ts:120-193.
// Phase 3 will swap each ModuleViewSpec for a server-fetched version.
function specForView(view: ActiveView): ModuleViewSpec | null {
  switch (view) {
    case "projectView":
      return {
        title: "项目管理",
        subtitle: "目标、里程碑、风险与交付物。",
        action: "+ 新建里程碑",
        cards: [
          {
            title: "当前目标",
            rows: [
              { title: "Q3 智能助手 v3.0 上线", meta: "68%" },
              { title: "首次方案刺激安排", meta: "进行中" },
            ],
          },
          {
            title: "开放风险",
            rows: [
              { title: "模型置信度评估不足", meta: "高" },
              { title: "知识图谱同步延迟", meta: "中" },
            ],
          },
          {
            title: "项目资源",
            body: "技术评审资源偏紧。新功能进入开发前建议先保持 L2 容量确认。",
          },
        ],
      };
    case "taskView":
      return {
        title: "任务视图",
        subtitle: "个人计划、团队可见、容量确认与正式承诺。",
        action: "+ 新建任务",
        cards: [
          {
            title: "L0 个人计划",
            rows: [{ title: "整理竞品帮助验证", meta: "个人" }],
          },
          {
            title: "L2 容量确认",
            rows: [{ title: "后端接口可行性评审", meta: "待 Blake" }],
          },
          {
            title: "L3 正式承诺",
            rows: [{ title: "CRM 后端接口对接", meta: "进行中" }],
          },
        ],
      };
    case "knowledgeView":
      return {
        title: "知识库",
        subtitle: "AI 可调用依据与团队记忆。",
        action: "+ 添加来源",
        twoColumn: true,
        cards: [
          {
            title: "最近调用",
            rows: [
              { title: "Boss-3 智能设计实践 v0.3", meta: "1 分钟前" },
              { title: "团队标准 · 合作规范 v2.1", meta: "10 分钟前" },
            ],
          },
          {
            title: "上下文策略",
            body: "个人草稿默认私有；外部反馈默认弱信号；已确认规格可作为项目依据进入当前工作记忆。",
          },
        ],
      };
    case "orgView":
      return {
        title: "组织管理",
        subtitle: "技能图谱、权限控制、成员角色与技术边界规则。",
        action: "+ 邀请成员",
        cards: [
          {
            title: "技能图谱",
            rows: [{ title: "后端架构", meta: "Blake · 9.2" }],
          },
          {
            title: "权限控制",
            rows: [{ title: "技术上下文 L1", meta: "产品可见" }],
          },
          {
            title: "成员负载",
            body: "Blake 有 2 个协同请求待处理。建议新增技术评审保持 L2。",
          },
        ],
      };
    case "auditView":
      return {
        title: "审计视图",
        subtitle: "高影响动作、确认人、上下文来源与图谱写入结果。",
        action: "导出记录",
        cards: [
          {
            title: "审计记录",
            rows: [
              { title: "智能助手技术方案：personal → proposed", meta: "待 Blake" },
              { title: "用户调研摘要：visible → knowledge", meta: "已写入" },
            ],
          },
        ],
      };
    case "agentView":
      return null;
  }
}

interface Props {
  view: ActiveView;
}

export function ModuleView({ view }: Props) {
  const t = useTranslations("shellVNext");
  const spec = specForView(view);
  if (!spec) return null;

  return (
    <section className={styles.module} data-testid={`vnext-module-${view}`}>
      <div className={styles.moduleHeader}>
        <div>
          <h2>{spec.title}</h2>
          <p>{spec.subtitle}</p>
        </div>
        {spec.action && (
          <button type="button" className={styles.actionBtn}>
            {spec.action}
          </button>
        )}
      </div>
      <p className={styles.placeholderHint}>{t("module.placeholderHint")}</p>
      <div
        className={`${styles.moduleGrid} ${spec.twoColumn ? styles.gridTwo : ""}`}
      >
        {spec.cards.map((card) => (
          <div key={card.title} className={styles.moduleCard}>
            <h3>{card.title}</h3>
            {card.body && <p>{card.body}</p>}
            {card.rows?.map((row) => (
              <div key={row.title} className={styles.moduleRow}>
                <strong>{row.title}</strong>
                <span>{row.meta}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
