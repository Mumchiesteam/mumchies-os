import { createContext, useContext } from 'react'

export type AuthUser = { username: string; display_name: string; role: 'owner' | 'admin' | 'operator' }

export const AuthContext = createContext<AuthUser | null>(null)
export const useAuth = () => useContext(AuthContext)
