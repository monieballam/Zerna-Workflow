import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Sidebar from '@/components/nav/Sidebar';

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
}));

describe('Sidebar', () => {
  it('always shows the feedback navigation entry', () => {
    render(<Sidebar isAdmin={false} />);
    expect(screen.getByRole('link', { name: /feedback/i })).toHaveAttribute('href', '/feedback');
  });

  it('only shows the admin entry for admins', () => {
    const { rerender } = render(<Sidebar isAdmin={false} />);
    expect(screen.queryByRole('link', { name: /admin/i })).not.toBeInTheDocument();

    rerender(<Sidebar isAdmin />);
    expect(screen.getByRole('link', { name: /admin/i })).toHaveAttribute('href', '/admin');
  });
});
