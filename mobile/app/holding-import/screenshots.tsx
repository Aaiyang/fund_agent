import { router } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import { Image, Pressable, Text, View } from 'react-native';

import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useUploadScreenshots, type PickedImage } from '@/hooks/useImports';
import { useAccounts } from '@/hooks/usePortfolio';

const MAX_IMAGES = 5;
const MAX_BYTES = 8 * 1024 * 1024;

/**
 * Screenshot upload. The backend answers 202 + import_id and parses in a
 * worker; this screen only hands the batch over (spec 7.9).
 */
export default function ScreenshotImportScreen() {
  const accounts = useAccounts();
  const upload = useUploadScreenshots();
  const [accountId, setAccountId] = useState<number | null>(null);
  const [sourceApp, setSourceApp] = useState('');
  const [images, setImages] = useState<PickedImage[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  const chosen = accountId ?? accounts.data?.items[0]?.id ?? null;

  async function pick() {
    setProblem(null);
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setProblem('需要相册权限才能读取持仓截图');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsMultipleSelection: true,
      quality: 1,
    });
    if (result.canceled || !result.assets?.length) return;

    const picked: PickedImage[] = result.assets.map((asset) => ({
      uri: asset.uri,
      name: asset.fileName ?? `holding-${Date.now()}-${images.length}.jpg`,
      mimeType: asset.mimeType ?? 'image/jpeg',
    }));
    const oversized = result.assets.filter((asset) => (asset.fileSize ?? 0) > MAX_BYTES);
    if (oversized.length > 0) {
      setProblem(`${oversized.length} 张图片超过 8MB，请先压缩后再上传`);
      return;
    }
    const merged = [...images, ...picked];
    if (merged.length > MAX_IMAGES) {
      setProblem(`一次最多上传 ${MAX_IMAGES} 张截图`);
      return;
    }
    setImages(merged);
  }

  function submit() {
    setProblem(null);
    if (chosen === null) {
      setProblem('请选择持仓账户');
      return;
    }
    if (images.length === 0) {
      setProblem('请先选择至少一张持仓截图');
      return;
    }
    upload.mutate(
      { accountId: chosen, sourceApp: sourceApp.trim() || null, images },
      {
        onSuccess: (accepted) => router.replace(`/holding-import/${accepted.import_id}`),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  return (
    <Screen>
      <Card>
        <SectionTitle title="识别账户与来源" />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {(accounts.data?.items ?? []).map((account) => (
            <Chip key={account.id} label={account.name} active={chosen === account.id} onPress={() => setAccountId(account.id)} />
          ))}
          <Chip label="+ 新增账户" onPress={() => router.push('/account/add')} />
        </View>
        <Field label="来源应用标签（可选）" value={sourceApp} onChangeText={setSourceApp} placeholder="支付宝 / 天天基金 / 银行" />
      </Card>

      <Card>
        <SectionTitle title={`截图（${images.length}/${MAX_IMAGES}）`} />
        <Text style={{ fontSize: 12, color: theme.textMuted, marginBottom: 10 }}>
          支持多张：系统会按基金代码去重合并，单张失败不影响其余结果。原图仅临时保存，识别或确认后自动删除，不写入数据库。
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {images.map((image) => (
            <Pressable key={image.uri} onPress={() => setImages((current) => current.filter((item) => item.uri !== image.uri))}>
              <Image source={{ uri: image.uri }} style={{ width: 96, height: 128, marginRight: 8, marginBottom: 8, borderRadius: 8 }} />
            </Pressable>
          ))}
        </View>
        <Button label="选择截图" variant="secondary" onPress={pick} />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginTop: 12 }}>{problem}</Text> : null}
        <Button label="开始识别" onPress={submit} loading={upload.isPending} />
      </Card>
    </Screen>
  );
}
