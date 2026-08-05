"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import clsx from "clsx";
import { Check, ChevronDown } from "lucide-react";
import {
  Children,
  forwardRef,
  isValidElement,
  useState,
  type ChangeEvent,
  type ReactElement,
  type SelectHTMLAttributes,
} from "react";

export interface NativeSelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value" | "defaultValue" | "children"> {
  value?: string;
  defaultValue?: string;
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
  children?: React.ReactNode;
}

type OptionProps = { value?: string; disabled?: boolean; children?: React.ReactNode };

/**
 * Custom select with the old NativeSelect API, so forms can migrate without
 * changing their option definitions. It keeps a hidden input for server
 * actions while Radix provides reliable keyboard and pointer behavior.
 */
export const NativeSelect = forwardRef<HTMLButtonElement, NativeSelectProps>(
  (
    {
      className,
      children,
      value,
      defaultValue,
      onChange,
      name,
      id,
      disabled,
      required,
      ...props
    },
    ref,
  ) => {
    const options = Children.toArray(children).filter(isValidElement) as ReactElement<OptionProps>[];
    const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue ?? "");
    const selectedValue = value ?? uncontrolledValue;
    const selectedOption = options.find((option) => option.props.value === selectedValue);

    const changeValue = (nextValue: string) => {
      if (value === undefined) setUncontrolledValue(nextValue);
      onChange?.({
        target: { value: nextValue },
        currentTarget: { value: nextValue },
      } as ChangeEvent<HTMLSelectElement>);
    };

    return (
      <SelectPrimitive.Root
        value={selectedValue || undefined}
        onValueChange={changeValue}
        disabled={disabled}
        required={required}
        name={name}
      >
        <SelectPrimitive.Trigger
          ref={ref}
          id={id}
          aria-label={props["aria-label"]}
          aria-labelledby={props["aria-labelledby"]}
          className={clsx(
            "inline-flex h-8 items-center justify-between gap-2 border border-line bg-surface-1 px-2.5 text-left text-sm text-fg",
            "focus-visible:border-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal",
            "disabled:cursor-not-allowed disabled:opacity-40",
            className,
          )}
        >
          <SelectPrimitive.Value placeholder={selectedOption?.props.children ?? "Select…"} />
          <SelectPrimitive.Icon>
            <ChevronDown size={13} className="text-fg-subtle" aria-hidden="true" />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>

        <SelectPrimitive.Portal>
          <SelectPrimitive.Content
            position="popper"
            sideOffset={4}
            className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden border border-line bg-surface-1 p-1 shadow-2xl shadow-black/30"
          >
            <SelectPrimitive.Viewport className="max-h-72">
              {options.map((option, index) => {
                const optionValue = option.props.value ?? `option-${index}`;
                return (
                  <SelectPrimitive.Item
                    key={optionValue}
                    value={optionValue}
                    disabled={option.props.disabled}
                    className="relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-7 pr-2 text-sm text-fg-muted outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-surface-2 data-[highlighted]:text-fg data-[disabled]:opacity-40"
                  >
                    <SelectPrimitive.ItemIndicator className="absolute left-2 inline-flex items-center">
                      <Check size={13} className="text-signal" aria-hidden="true" />
                    </SelectPrimitive.ItemIndicator>
                    <SelectPrimitive.ItemText>{option.props.children}</SelectPrimitive.ItemText>
                  </SelectPrimitive.Item>
                );
              })}
            </SelectPrimitive.Viewport>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>

        {name ? <input type="hidden" name={name} value={selectedValue} /> : null}
      </SelectPrimitive.Root>
    );
  },
);

NativeSelect.displayName = "NativeSelect";
