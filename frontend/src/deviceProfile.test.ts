import test from 'node:test'
import assert from 'node:assert/strict'
import { parseDeviceProfile } from './deviceProfile.ts'

const caregiverId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const patientId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

test('a device can remember either role with a separate linked patient selection', () => {
  for (const mode of ['caregiver', 'patient']) {
    const profile = { caregiverId, caregiverName: 'Alex', patientId, mode }
    assert.deepEqual(parseDeviceProfile(JSON.stringify(profile)), profile)
  }
  assert.deepEqual(parseDeviceProfile(JSON.stringify({ caregiverId, caregiverName: 'Alex', patientId: null, mode: 'caregiver' })),
    { caregiverId, caregiverName: 'Alex', patientId: null, mode: 'caregiver' })
})

test('broken or unsafe stored selections return to onboarding instead of a demo patient', () => {
  for (const value of [null, '', '{', 'null', '[]', '{}',
    JSON.stringify({ caregiverId: '../other', caregiverName: 'Alex', patientId, mode: 'patient' }),
    JSON.stringify({ caregiverId, caregiverName: '', patientId, mode: 'caregiver' }),
    JSON.stringify({ caregiverId, caregiverName: 'Alex', patientId, mode: 'administrator' }),
    JSON.stringify({ caregiverId, caregiverName: 'Alex', patientId: 'invalid', mode: 'patient' })]) {
    assert.equal(parseDeviceProfile(value), null)
  }
})

test('stored device choices do not restore profile data or conversation context', () => {
  const result = parseDeviceProfile(JSON.stringify({ caregiverId, caregiverName: 'Alex', patientId, mode: 'patient',
    favorites: { foods: ['sample'] }, transcript: 'not a stored field' }))!
  assert.deepEqual(Object.keys(result).sort(), ['caregiverId', 'caregiverName', 'mode', 'patientId'])
})
