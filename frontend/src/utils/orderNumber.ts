export const orderNumberClipboardValue = (value: string | number) => String(value).replace(/^#/, '')
export const displayedOrderNumber = (value: string | number) => `#${orderNumberClipboardValue(value)}`

export const stopCopyPropagation = (event: { stopPropagation: () => void }, enabled: boolean) => {
  if (enabled) event.stopPropagation()
}
