'use client';

import React, { InputHTMLAttributes, forwardRef } from 'react';
import { cn } from '@/lib/utils';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  description?: string;
  error?: string;
  leftElement?: React.ReactNode;
  rightElement?: React.ReactNode;
  fullWidth?: boolean;
}

/**
 * 输入框组件 - 基础表单输入组件
 *
 * @example
 * <Input label="Email" type="email" placeholder="Enter your email" />
 * <Input label="Search" leftElement={<SearchIcon />} />
 * <Input label="Password" error="Password is required" />
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className,
      type = 'text',
      label,
      description,
      error,
      leftElement,
      rightElement,
      fullWidth = false,
      disabled,
      ...props
    },
    ref
  ) => {
    const hasLeftElement = !!leftElement;
    const hasRightElement = !!rightElement;
    const hasError = !!error;

    return (
      <div className={cn('w-full', fullWidth && 'w-full')}>
        {label && (
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {label}
          </label>
        )}
        <div
          className={cn(
            'relative flex items-center',
            'rounded-lg border bg-white dark:bg-gray-900',
            hasError
              ? 'border-red-500 focus-within:border-red-600 focus-within:ring-1 focus-within:ring-red-500'
              : 'border-gray-300 dark:border-gray-700 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500',
            'transition-colors',
            disabled && 'bg-gray-100 dark:bg-gray-800 cursor-not-allowed',
            className
          )}
        >
          {hasLeftElement && (
            <div className="pl-3 text-gray-400 dark:text-gray-500 flex-shrink-0">
              {leftElement}
            </div>
          )}
          <input
            ref={ref}
            type={type}
            disabled={disabled}
            className={cn(
              'w-full px-3 py-2 text-sm text-gray-900 dark:text-gray-100',
              'placeholder:text-gray-400 dark:placeholder:text-gray-600',
              'focus:outline-none bg-transparent',
              hasLeftElement && 'pl-2',
              hasRightElement && 'pr-2',
              'rounded-lg'
            )}
            {...props}
          />
          {hasRightElement && (
            <div className="pr-3 text-gray-400 dark:text-gray-500 flex-shrink-0">
              {rightElement}
            </div>
          )}
        </div>
        {description && !hasError && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p>
        )}
        {hasError && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';

/**
 * 文本域组件
 */
export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  description?: string;
  error?: string;
  fullWidth?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  (
    {
      className,
      label,
      description,
      error,
      fullWidth = false,
      disabled,
      rows = 4,
      ...props
    },
    ref
  ) => {
    const hasError = !!error;

    return (
      <div className={cn('w-full', fullWidth && 'w-full')}>
        {label && (
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          rows={rows}
          disabled={disabled}
          className={cn(
            'w-full px-3 py-2 text-sm text-gray-900 dark:text-gray-100',
            'placeholder:text-gray-400 dark:placeholder:text-gray-600',
            'focus:outline-none focus:ring-1 focus:ring-blue-500',
            'rounded-lg border bg-white dark:bg-gray-900',
            hasError
              ? 'border-red-500 focus:ring-red-500'
              : 'border-gray-300 dark:border-gray-700',
            'transition-colors resize-y',
            disabled && 'bg-gray-100 dark:bg-gray-800 cursor-not-allowed',
            className
          )}
          {...props}
        />
        {description && !hasError && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p>
        )}
        {hasError && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';

/**
 * 选择框组件
 */
export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  description?: string;
  error?: string;
  options?: { value: string; label: string; disabled?: boolean }[];
  fullWidth?: boolean;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      className,
      label,
      description,
      error,
      options = [],
      fullWidth = false,
      disabled,
      ...props
    },
    ref
  ) => {
    const hasError = !!error;

    return (
      <div className={cn('w-full', fullWidth && 'w-full')}>
        {label && (
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {label}
          </label>
        )}
        <select
          ref={ref}
          disabled={disabled}
          className={cn(
            'w-full px-3 py-2 text-sm text-gray-900 dark:text-gray-100',
            'focus:outline-none focus:ring-1 focus:ring-blue-500',
            'rounded-lg border bg-white dark:bg-gray-900',
            hasError
              ? 'border-red-500 focus:ring-red-500'
              : 'border-gray-300 dark:border-gray-700',
            'transition-colors appearance-none',
            disabled && 'bg-gray-100 dark:bg-gray-800 cursor-not-allowed',
            'bg-[url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIGZpbGw9Im5vbmUiIHZpZXdCb3g9IjAgMCAyNCAyNCIgc3Ryb2tlPSJjdXJyZW50Q29sb3IiPjxwYXRoIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIyIiBkPSJNMTkgOWwtNyA3LTctNyIvPjwvc3ZnPg==)] bg-[length:1.25rem_1.25rem] bg-[right_0.5rem_center] bg-no-repeat pr-10',
            className
          )}
          {...props}
        >
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={option.disabled}
            >
              {option.label}
            </option>
          ))}
        </select>
        {description && !hasError && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p>
        )}
        {hasError && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }
);

Select.displayName = 'Select';
