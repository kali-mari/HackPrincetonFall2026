export type DeviceMode = 'caregiver' | 'patient'
export type DeviceProfile = { caregiverId: string; caregiverName: string; patientId: string | null; mode: DeviceMode }
export const DEVICE_PROFILE_KEY = 'aac-device-profile-v1'
export const validProfileId = (value: unknown): value is string => typeof value === 'string'
  && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)

export function parseDeviceProfile(value: string | null): DeviceProfile | null {
  try {
    const data = JSON.parse(value ?? 'null')
    if (!data || !validProfileId(data.caregiverId) || (data.patientId !== null && !validProfileId(data.patientId))
      || !['caregiver', 'patient'].includes(data.mode) || typeof data.caregiverName !== 'string'
      || !data.caregiverName.trim() || data.caregiverName.length > 80) return null
    return { caregiverId: data.caregiverId, caregiverName: data.caregiverName, patientId: data.patientId, mode: data.mode }
  } catch {
    return null
  }
}

export function readDeviceProfile(): DeviceProfile | null {
  try { return parseDeviceProfile(localStorage.getItem(DEVICE_PROFILE_KEY)) } catch { return null }
}

export function rememberDeviceProfile(profile: DeviceProfile) {
  try { localStorage.setItem(DEVICE_PROFILE_KEY, JSON.stringify(profile)) } catch { /* Session still works. */ }
}
