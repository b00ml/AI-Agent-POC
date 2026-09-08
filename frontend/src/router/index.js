import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/m2',
  },
  {
    path: '/m2',
    name: 'M2Audit',
    component: () => import('../views/M2Audit.vue'),
    meta: { title: 'M2 合规审核', icon: 'Document' },
  },
  {
    path: '/m2/:claimId',
    name: 'M2Detail',
    component: () => import('../views/M2Detail.vue'),
    meta: { title: '审核详情', hidden: true },
  },
  {
    path: '/m3',
    name: 'M3Anomaly',
    component: () => import('../views/M3Anomaly.vue'),
    meta: { title: 'M3 异常检测', icon: 'Warning' },
  },
  {
    path: '/m4',
    name: 'M4Analytics',
    component: () => import('../views/M4Analytics.vue'),
    meta: { title: 'M4 银行对账', icon: 'DataAnalysis' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { title: '系统设置', icon: 'Setting' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
