let csrfToken = ''

export const getCsrfToken = () => csrfToken
export const setCsrfToken = (value: string) => {
  csrfToken = value
}
