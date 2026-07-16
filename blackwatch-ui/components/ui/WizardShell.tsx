"use client";

import clsx from "clsx";
import { ReactNode } from "react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { BackLink } from "@/components/ui/BackLink";
import { DataPanel } from "@/components/layout/DataPanel";

export type WizardStepDef = { n: number; label: string };

export function Wizard({
  backHref,
  backLabel,
  title,
  subtitle,
  steps,
  current,
  completed,
  onJump,
  onBack,
  onNext,
  canAdvance,
  isFinal,
  finalNode,
  children,
}: {
  backHref: string;
  backLabel: string;
  title: string;
  subtitle?: string;
  steps: WizardStepDef[];
  current: number;
  completed: Record<number, boolean>;
  onJump: (n: number) => void;
  onBack: () => void;
  onNext: () => void;
  canAdvance: boolean;
  isFinal: boolean;
  finalNode: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-3xl">
      <BackLink href={backHref} label={backLabel} />

      <div className="mb-8">
        <h1 className="text-xl text-fg">{title}</h1>
        {subtitle && <p className="mt-1 text-xs text-fg-muted">{subtitle}</p>}
      </div>

      <WizardStepper
        steps={steps}
        current={current}
        completed={completed}
        onJump={onJump}
      />

      <DataPanel scrollX={false}>
        <div className="p-8">{children}</div>
      </DataPanel>

      <div className="mt-4 flex items-center justify-between">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={current === steps[0].n}
          onClick={onBack}
        >
          <ArrowLeft size={12} /> Back
        </Button>

        {isFinal ? (
          finalNode
        ) : (
          <Button
            type="button"
            size="sm"
            variant="primary"
            disabled={!canAdvance}
            onClick={onNext}
          >
            Next <ArrowRight size={12} />
          </Button>
        )}
      </div>
    </div>
  );
}

export function WizardStepHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-5">
      <h2 className="text-sm text-fg">{title}</h2>
      {subtitle && <p className="mt-1 text-xs text-fg-muted">{subtitle}</p>}
    </div>
  );
}

function WizardStepper({
  steps,
  current,
  completed,
  onJump,
}: {
  steps: WizardStepDef[];
  current: number;
  completed: Record<number, boolean>;
  onJump: (n: number) => void;
}) {
  return (
    <nav aria-label="Progress" className="mb-8">
      <ol className="flex items-start">
        {steps.map((s, i) => {
          const active = current === s.n;
          const done = !!completed[s.n] && !active;
          const isLast = i === steps.length - 1;

          return (
            <li
              key={s.n}
              className={clsx("flex items-start", !isLast && "flex-1")}
            >
              <button
                type="button"
                onClick={() => onJump(s.n)}
                className="group flex flex-col items-center gap-1.5"
                aria-current={active ? "step" : undefined}
              >
                <span
                  className={clsx(
                    "flex h-7 w-7 items-center justify-center rounded-full border-2 font-mono text-[11px] transition-colors",
                    active
                      ? "border-signal bg-signal text-canvas"
                      : done
                        ? "border-signal/50 bg-signal/10 text-signal"
                        : "border-line-soft text-fg-subtle group-hover:border-line",
                  )}
                >
                  {done ? <Check size={11} strokeWidth={2.5} /> : s.n}
                </span>
                <span
                  className={clsx(
                    "text-[10px] uppercase tracking-[0.08em]",
                    active
                      ? "text-fg"
                      : done
                        ? "text-fg-muted"
                        : "text-fg-subtle",
                  )}
                >
                  {s.label}
                </span>
              </button>
              {!isLast && (
                <div
                  className={clsx(
                    "mx-1.5 mt-3.5 h-px flex-1 transition-colors",
                    done ? "bg-signal/30" : "bg-line-soft",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
