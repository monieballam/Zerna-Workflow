import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import RunStatusBadge from '@/components/runs/RunStatusBadge';

describe('RunStatusBadge', () => {
  it.each([
    ['queued', /queued/i],
    ['running', /running/i],
    ['completed', /completed/i],
    ['failed', /failed/i],
    ['cancelled', /cancelled/i],
  ] as const)('renders %s status', (status, pattern) => {
    render(<RunStatusBadge status={status} />);
    expect(screen.getByText(pattern)).toBeInTheDocument();
  });

  it('shows pulse indicator for running status', () => {
    const { container } = render(<RunStatusBadge status="running" />);
    const pulse = container.querySelector('.animate-pulse');
    expect(pulse).toBeInTheDocument();
  });

  it('does not show pulse for non-running statuses', () => {
    const { container } = render(<RunStatusBadge status="completed" />);
    expect(container.querySelector('.animate-pulse')).not.toBeInTheDocument();
  });
});
