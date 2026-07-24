"use client";

import { useState } from "react";
import { BookOpen, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

const SECTIONS: { title: string; items: string[] }[] = [
  {
    title: "核心理念：趋势定方向，RSI 定时机",
    items: [
      "RSI 是动量/情绪指标，超买/超卖只是环境信号，不是交易信号",
      "EMA200 定义大趋势方向，只在趋势方向上使用 RSI「离开极端区域」的信号",
      "顺势交易 + 动量确认 = 高胜率组合，拒绝逆势抄底摸顶",
    ],
  },
  {
    title: "多头入场（全部满足）",
    items: [
      "收盘价站上 EMA200（确认多头环境）",
      "RSI(14) 从 30 下方向上穿越 30（离开超卖区）",
      "可选加强：K线收阳，或价格同时站上 EMA50",
    ],
  },
  {
    title: "空头入场（对称）",
    items: [
      "收盘价跌破 EMA200（确认空头环境）",
      "RSI(14) 从 70 上方向下穿越 70（离开超买区）",
      "可选加强：K线收阴，或价格同时跌破 EMA50",
    ],
  },
  {
    title: "止损与止盈",
    items: [
      "止损：入场K线最低/最高点外 1–1.5 倍 ATR",
      "第一目标：1:2 盈亏比；之后可减仓 50%，剩余仓位移动止损让利润奔跑",
      "RSI 再次进入极端区域（多单 >70 / 空单 <30）时减仓",
      "价格反向穿越 EMA200 立即平仓（趋势环境改变）",
    ],
  },
  {
    title: "仓位纪律与注意事项",
    items: [
      "单笔风险严格控制在总资金的 0.5%–1%",
      "同一方向最多持有 1–2 单，避免过度集中",
      "EMA200 附近反复缠绕的震荡市暂停交易",
      "历史回测不代表未来收益，严格执行纪律比策略本身更重要",
    ],
  },
];

export function MethodologyCard({ className }: { className?: string }) {
  const [open, setOpen] = useState(true);

  return (
    <section className={cn("glass-card p-5 sm:p-6", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5">
          <BookOpen className="h-5 w-5 text-cy" />
          <div>
            <h2 className="text-lg font-semibold text-foreground">策略方法论</h2>
            <p className="text-sm text-muted-foreground">
              颠覆 RSI 传统用法：EMA200 过滤逆势信号，只做顺势动量确认
            </p>
          </div>
        </div>
        {open ? (
          <ChevronUp className="h-5 w-5 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-5 w-5 text-muted-foreground" />
        )}
      </button>

      {open && (
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {SECTIONS.map((section) => (
            <div key={section.title} className="rounded-xl bg-elevated p-4">
              <h3 className="text-sm font-semibold text-foreground">{section.title}</h3>
              <ul className="mt-2 space-y-1.5">
                {section.items.map((item) => (
                  <li
                    key={item}
                    className="flex gap-2 text-xs leading-relaxed text-muted-foreground"
                  >
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-cy" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
