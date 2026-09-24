'use client';

import Link from 'next/link';
import { useFormState, useFormStatus } from 'react-dom';
import { signupAction, type SignupState } from '@/lib/actions';

const initialState: SignupState = {};

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} className="btn-primary w-full">
      {pending ? 'Creating account…' : 'Create account'}
    </button>
  );
}

export default function SignupForm() {
  const [state, formAction] = useFormState(signupAction, initialState);

  return (
    <form action={formAction} className="space-y-5">
      {state.error && (
        <div
          role="alert"
          className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
        >
          {state.error}
        </div>
      )}

      <div>
        <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
          Email address
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          className="input-field"
          placeholder="you@example.com"
        />
      </div>

      <div>
        <label htmlFor="organizationName" className="block text-sm font-medium text-gray-700 mb-1">
          Workspace name
        </label>
        <input
          id="organizationName"
          name="organizationName"
          type="text"
          autoComplete="organization"
          className="input-field"
          placeholder="Optional, e.g. Hamid Lab"
        />
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          className="input-field"
          placeholder="At least 8 characters"
        />
      </div>

      <div>
        <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700 mb-1">
          Confirm password
        </label>
        <input
          id="confirmPassword"
          name="confirmPassword"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          className="input-field"
          placeholder="Repeat your password"
        />
      </div>

      <SubmitButton />

      <p className="text-center text-sm text-gray-600">
        Already have an account?{' '}
        <Link href="/login" className="text-primary-700 hover:text-primary-800 font-medium">
          Sign in
        </Link>
      </p>
    </form>
  );
}
