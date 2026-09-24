import OrgSelector from './OrgSelector';
import UserMenu from './UserMenu';

interface NavbarProps {
  email?: string;
  orgs?: Array<{ id: string; name: string }>;
  currentOrgId?: string;
}

export default function Navbar({ email, orgs, currentOrgId }: NavbarProps) {
  return (
    <header className="h-14 border-b border-gray-200 bg-white flex items-center px-4 gap-4 shrink-0 z-30">
      {/* Brand */}
      <div className="flex items-center gap-2 mr-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-600">
          <svg
            className="h-4 w-4 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"
            />
          </svg>
        </div>
        <span className="font-bold text-gray-900 text-sm">Zerna</span>
      </div>

      {/* Org selector */}
      <OrgSelector orgs={orgs} currentOrgId={currentOrgId} />

      {/* Spacer */}
      <div className="flex-1" />

      {/* User menu */}
      <UserMenu email={email} />
    </header>
  );
}
