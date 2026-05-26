'use client';

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { cn } from '@/lib/utils';

export interface DropdownProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: 'left' | 'right';
  width?: 'sm' | 'md' | 'lg' | 'full';
  closeOnSelect?: boolean;
  className?: string;
}

/**
 * 下拉菜单组件
 *
 * @example
 * <Dropdown trigger={<Button>Menu</Button>}>
 *   <Dropdown.Item>Action 1</Dropdown.Item>
 *   <Dropdown.Item>Action 2</Dropdown.Item>
 * </Dropdown>
 */
export function Dropdown({
  trigger,
  children,
  align = 'left',
  width = 'md',
  closeOnSelect = true,
  className,
}: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // ESC 键关闭
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen]);

  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  const handleSelect = useCallback(() => {
    if (closeOnSelect) {
      setIsOpen(false);
    }
  }, [closeOnSelect]);

  const widthStyles = {
    sm: 'min-w-[160px]',
    md: 'min-w-[200px]',
    lg: 'min-w-[280px]',
    full: 'w-full',
  };

  const alignStyles = {
    left: 'left-0 origin-top-left',
    right: 'right-0 origin-top-right',
  };

  return (
    <div ref={dropdownRef} className={cn('relative inline-block', className)}>
      <div onClick={toggle} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && toggle()}>
        {trigger}
      </div>

      {isOpen && (
        <div
          className={cn(
            'absolute z-50 mt-2 rounded-lg border border-gray-200 dark:border-gray-800',
            'bg-white dark:bg-gray-900 shadow-lg',
            'py-1 max-h-[calc(100vh-200px)] overflow-y-auto',
            widthStyles[width],
            alignStyles[align]
          )}
        >
          {React.Children.map(children, (child) => {
            if (React.isValidElement<DropdownItemProps>(child)) {
              return React.cloneElement<DropdownItemProps>(child, {
                onSelect: handleSelect,
              });
            }
            return child;
          })}
        </div>
      )}
    </div>
  );
}

export interface DropdownItemProps {
  children?: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
  divider?: boolean;
  onSelect?: () => void;
  onClick?: () => void;
  className?: string;
}

/**
 * 下拉菜单项
 */
export function DropdownItem({
  children,
  icon,
  disabled = false,
  divider = false,
  onSelect,
  onClick,
  className,
}: DropdownItemProps) {
  const handleClick = useCallback(() => {
    if (!disabled) {
      onClick?.();
      onSelect?.();
    }
  }, [disabled, onClick, onSelect]);

  if (divider) {
    return <div className="my-1 h-px bg-gray-200 dark:bg-gray-800" />;
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      className={cn(
        'w-full flex items-center gap-3 px-4 py-2 text-sm',
        'text-gray-700 dark:text-gray-300',
        'hover:bg-gray-100 dark:hover:bg-gray-800',
        'focus:outline-none focus:bg-gray-100 dark:focus:bg-gray-800',
        disabled && 'text-gray-400 dark:text-gray-600 cursor-not-allowed',
        className
      )}
    >
      {icon && <span className="flex-shrink-0 w-5 h-5">{icon}</span>}
      <span className="flex-1 text-left">{children}</span>
    </button>
  );
}

Dropdown.Item = DropdownItem;

/**
 * 下拉菜单分割线
 */
export function DropdownDivider() {
  return <DropdownItem divider />;
}

Dropdown.Divider = DropdownDivider;

/**
 * 下拉菜单头部
 */
export interface DropdownHeaderProps {
  children: React.ReactNode;
  className?: string;
}

export function DropdownHeader({ children, className }: DropdownHeaderProps) {
  return (
    <div
      className={cn(
        'px-4 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider',
        className
      )}
    >
      {children}
    </div>
  );
}

Dropdown.Header = DropdownHeader;
